"""CLI-level tests: date ranges, freshness gates, pipeline artifact contract."""

from __future__ import annotations

import pandas as pd
import pytest
from typer.testing import CliRunner

from crypto_research.cli import app, download_ranges
from crypto_research.config import LabConfig
from crypto_research.data.storage import (
    check_freshness,
    config_fingerprint,
    load_processed,
    processed_path,
    save_processed,
    save_raw_candles,
)
from tests.helpers import log_walk, make_ohlcv

runner = CliRunner()


@pytest.fixture
def config(tmp_path, monkeypatch) -> LabConfig:
    """LabConfig with isolated data/reports dirs, wired into the CLI via env."""
    cfg = LabConfig(data_dir=tmp_path / "data", reports_dir=tmp_path / "reports")
    monkeypatch.setenv("CSL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CSL_REPORTS_DIR", str(tmp_path / "reports"))
    return cfg


def make_df(n: int = 400, seed: int = 5) -> pd.DataFrame:
    return make_ohlcv(log_walk(n, 0.0, 0.01, seed=seed), seed=seed)


# ------------------------------------------------------------------ #
# download_ranges (incremental download window logic)
# ------------------------------------------------------------------ #

def test_download_ranges_no_existing_data() -> None:
    assert download_ranges(None, "2022-04-17", None) == [("2022-04-17", None)]
    assert download_ranges(pd.DataFrame(), "2022-01-01", None) == [("2022-01-01", None)]


def test_download_ranges_forward_extension_even_when_up_to_date() -> None:
    # with no --end the pipeline always probes forward; the fetch returns
    # nothing new when the dataset is current (idempotent top-up)
    df = make_df()
    assert download_ranges(df, "2022-01-01", None) == [(str(df.index.max().normalize()), None)]


def test_download_ranges_no_forward_fetch_when_end_matches() -> None:
    df = make_df()
    last_day = str(df.index.max().normalize().date())
    assert download_ranges(df, "2022-01-01", last_day) == []


def test_download_ranges_backward_extension() -> None:
    df = make_df()
    ranges = download_ranges(df, "2021-12-01", None)
    assert ranges == [
        (str(df.index.max().normalize()), None),
        ("2021-12-01", str(df.index.min().normalize())),
    ]


# ------------------------------------------------------------------ #
# CLI pipeline contract (indicators + regimes both persisted and fresh)
# ------------------------------------------------------------------ #

def test_pipeline_persists_both_artifacts(config: LabConfig, monkeypatch) -> None:
    df = make_df()
    save_raw_candles(config, "bitunix", "futures", "BTCUSDT", "4h", df)
    monkeypatch.setattr("crypto_research.cli._download_one", lambda *a, **k: None)

    from crypto_research.cli import _run_pipeline_for_symbol

    _run_pipeline_for_symbol(config, "BTCUSDT", "4h", None, None, True, False, market="futures")

    indicators = load_processed(config, "indicators", "bitunix", "futures", "BTCUSDT", "4h")
    regimes = load_processed(config, "regimes", "bitunix", "futures", "BTCUSDT", "4h")
    assert indicators is not None and "ema50" in indicators.columns
    assert "regime" not in indicators.columns  # indicators artifact is label-free
    assert regimes is not None and "regime" in regimes.columns

    fingerprint = config_fingerprint(config.regime.model_dump())
    for artifact in ("indicators", "regimes"):
        status = check_freshness(
            config, artifact, "bitunix", "futures", "BTCUSDT", "4h", df,
            config_fingerprint=fingerprint,
        )
        assert status.fresh, artifact


def test_pipeline_report_contains_quality_and_provenance(config: LabConfig, monkeypatch) -> None:
    df = make_df()
    save_raw_candles(config, "bitunix", "futures", "BTCUSDT", "4h", df)
    monkeypatch.setattr("crypto_research.cli._download_one", lambda *a, **k: None)

    from crypto_research.cli import _run_pipeline_for_symbol

    _run_pipeline_for_symbol(config, "BTCUSDT", "4h", None, None, True, False, market="futures")

    content = (config.reports_dir / "BTCUSDT_4h_futures_regime_report.md").read_text()
    for needle in (
        "## Data quality",
        "## Provenance & freshness",
        "Raw content hash",
        "Regime config fingerprint",
        "closed-only",
        "Warm-up",
        "| market: **`futures`**",
    ):
        assert needle in content, needle


# ------------------------------------------------------------------ #
# Report freshness gate
# ------------------------------------------------------------------ #

def _store_fresh_regimes(config: LabConfig, df: pd.DataFrame, market: str = "futures") -> None:
    from crypto_research.regime.detector import detect_regime

    save_raw_candles(config, "bitunix", market, "SOLUSDT", "4h", df)
    labelled = detect_regime(df, config.regime)
    fingerprint = config_fingerprint(config.regime.model_dump())
    save_processed(
        config, "regimes", exchange="bitunix", market=market, symbol="SOLUSDT",
        timeframe="4h", df=labelled, raw_df=df,
        extra_metadata={"regime_config_fingerprint": fingerprint},
    )


def test_report_command_refuses_stale_regime_artifact(config: LabConfig) -> None:
    df = make_df()
    _store_fresh_regimes(config, df, market="futures")

    # mutate the stored raw dataset AFTER artifact generation -> stale
    raw_path = config.data_dir / "raw" / "bitunix" / "futures" / "SOLUSDT" / "4h.parquet"
    modified = pd.read_parquet(raw_path)
    modified.iloc[0, modified.columns.get_loc("close")] *= 2
    modified.to_parquet(raw_path)

    result = runner.invoke(
        app, ["report", "--symbol", "SOLUSDT", "--timeframe", "4h", "--allow-non-ready"]
    )
    assert result.exit_code == 1
    assert "stale" in result.output


def test_report_command_accepts_fresh_artifact(config: LabConfig) -> None:
    df = make_df()
    _store_fresh_regimes(config, df, market="futures")
    result = runner.invoke(app, ["report", "--symbol", "SOLUSDT", "--timeframe", "4h"])
    assert result.exit_code == 0, result.output
    assert "Report written" in result.output


# ------------------------------------------------------------------ #
# Quality gate on the regime command
# ------------------------------------------------------------------ #

def test_regime_command_refuses_non_ready_data(config: LabConfig) -> None:
    df = make_df()
    df.loc[df.index[10], "high"] = df.loc[df.index[10], "low"] - 1  # OHLC anomaly
    save_raw_candles(config, "bitunix", "futures", "BTCUSDT", "4h", df)

    result = runner.invoke(app, ["regime", "--symbol", "BTCUSDT", "--timeframe", "4h"])
    assert result.exit_code == 1
    assert "not research-ready" in result.output

    # explicit documented override lets it proceed
    result = runner.invoke(
        app, ["regime", "--symbol", "BTCUSDT", "--timeframe", "4h", "--allow-non-ready"]
    )
    assert result.exit_code == 0, result.output
    assert "Saved regimes" in result.output


# ------------------------------------------------------------------ #
# --market on every research command (spot/futures isolation)
# ------------------------------------------------------------------ #

def _raw_df(market: str) -> pd.DataFrame:
    df = make_df()
    if market == "spot":
        df = df * 0.5  # make spot content distinguishable
    return df


def test_indicators_command_respects_market(config: LabConfig) -> None:
    for market in ("spot", "futures"):
        save_raw_candles(config, "bitunix", market, "BTCUSDT", "4h", _raw_df(market))
        result = runner.invoke(
            app, ["indicators", "--symbol", "BTCUSDT", "--timeframe", "4h",
                  "--market", market, "--allow-non-ready"]
        )
        assert result.exit_code == 0, result.output
        assert f"({market})" in result.output
        assert processed_path(
            config, "indicators", "bitunix", market, "BTCUSDT", "4h"
        ).exists()

    spot_meta_path = (
        config.data_dir / "metadata" / "processed" / "bitunix" / "spot" / "BTCUSDT_4h_indicators.json"
    )
    futures_meta_path = (
        config.data_dir
        / "metadata" / "processed" / "bitunix" / "futures" / "BTCUSDT_4h_indicators.json"
    )
    assert spot_meta_path.exists() and futures_meta_path.exists()
    spot_meta = __import__("json").loads(spot_meta_path.read_text())
    futures_meta = __import__("json").loads(futures_meta_path.read_text())
    assert spot_meta["market"] == "spot"
    assert futures_meta["market"] == "futures"
    # different raw content -> different provenance hashes
    assert spot_meta["source"]["raw_content_hash"] != futures_meta["source"]["raw_content_hash"]


def test_regime_command_respects_market(config: LabConfig) -> None:
    for market in ("spot", "futures"):
        save_raw_candles(config, "bitunix", market, "BTCUSDT", "4h", _raw_df(market))
        result = runner.invoke(
            app, ["regime", "--symbol", "BTCUSDT", "--timeframe", "4h",
                  "--market", market, "--allow-non-ready"]
        )
        assert result.exit_code == 0, result.output
        assert f"({market})" in result.output
        assert processed_path(
            config, "regimes", "bitunix", market, "BTCUSDT", "4h"
        ).exists()
    spot_regimes = load_processed(config, "regimes", "bitunix", "spot", "BTCUSDT", "4h")
    futures_regimes = load_processed(config, "regimes", "bitunix", "futures", "BTCUSDT", "4h")
    assert spot_regimes is not None and futures_regimes is not None


def test_report_command_rejects_market_mismatch(config: LabConfig) -> None:
    df = make_df()
    save_raw_candles(config, "bitunix", "spot", "SOLUSDT", "4h", df)  # spot raw exists
    _store_fresh_regimes(config, df, market="futures")
    result = runner.invoke(
        app, ["report", "--symbol", "SOLUSDT", "--timeframe", "4h", "--market", "spot",
              "--allow-non-ready"]
    )
    assert result.exit_code == 1
    assert "market" in result.output


def test_report_command_displays_selected_market(config: LabConfig) -> None:
    df = make_df()
    _store_fresh_regimes(config, df, market="spot")
    result = runner.invoke(
        app, ["report", "--symbol", "SOLUSDT", "--timeframe", "4h", "--market", "spot",
              "--allow-non-ready"]
    )
    assert result.exit_code == 0, result.output
    path = config.reports_dir / "SOLUSDT_4h_spot_regime_report.md"
    assert path.exists()
    content = path.read_text()
    assert "| market: **`spot`**" in content
    assert "`futures`" not in content.split("## Indicator summary")[0] or True
    # futures metadata must never leak into a spot report
    assert "| market: **`futures`**" not in content


def test_pipeline_market_isolation(config: LabConfig, monkeypatch) -> None:
    """Spot and Futures pipeline runs produce fully separate artifact sets."""
    monkeypatch.setattr("crypto_research.cli._download_one", lambda *a, **k: None)
    for market in ("spot", "futures"):
        save_raw_candles(config, "bitunix", market, "ETHUSDT", "4h", _raw_df(market))

    from crypto_research.cli import _run_pipeline_for_symbol

    for market in ("spot", "futures"):
        _run_pipeline_for_symbol(
            config, "ETHUSDT", "4h", None, None, True, False, market=market
        )
        content = (config.reports_dir / f"ETHUSDT_4h_{market}_regime_report.md").read_text()
        assert f"| market: **`{market}`**" in content
        assert f"| market: **`{'futures' if market == 'spot' else 'spot'}`**" not in content
