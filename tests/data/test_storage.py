"""Storage tests: merge semantics, atomic writes, metadata sidecars."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.config import LabConfig
from crypto_strategy_lab.data.storage import (
    StorageError,
    config_fingerprint,
    load_processed,
    load_raw_candles,
    merge_raw_candles,
    raw_candles_path,
    read_metadata,
    save_processed,
    save_raw_candles,
)
from tests.helpers import log_walk, make_ohlcv


@pytest.fixture
def config(tmp_path) -> LabConfig:
    return LabConfig(data_dir=tmp_path / "data", reports_dir=tmp_path / "reports")


def make_df(n: int = 300, seed: int = 5) -> pd.DataFrame:
    close = log_walk(n, 0.0, 0.01, seed=seed)
    return make_ohlcv(close, seed=seed)


def test_save_and_load_raw_roundtrip(config: LabConfig) -> None:
    df = make_df()
    _, path = save_raw_candles(config, "bitunix", "futures", "BTCUSDT", "4h", df)
    assert path.name == "4h.parquet"
    loaded = load_raw_candles(config, "bitunix", "futures", "BTCUSDT", "4h")
    assert loaded is not None and loaded.equals(df)


def test_save_raw_writes_metadata(config: LabConfig) -> None:
    df = make_df()
    _, path = save_raw_candles(config, "bitunix", "futures", "BTCUSDT", "4h", df)
    meta_path = config.data_dir / "metadata" / "raw" / "bitunix" / "futures" / "BTCUSDT_4h.json"
    metadata = read_metadata(meta_path)
    assert metadata is not None
    assert metadata["exchange"] == "bitunix"
    assert metadata["symbol"] == "BTCUSDT"
    assert metadata["timeframe"] == "4h"
    assert metadata["market"] == "futures"
    assert metadata["rows"] == len(df)
    assert metadata["schema_version"] == "1.0"
    assert metadata["start"] == str(df.index.min())
    assert metadata["end"] == str(df.index.max())
    assert metadata["candles_policy"] == "closed-only"
    assert metadata["research_ready"] is True
    assert len(metadata["raw_content_hash"]) == 64
    json.loads(meta_path.read_text())  # valid JSON


def test_incremental_save_merges_deduplicates_and_refreshes_tail(config: LabConfig) -> None:
    df = make_df()
    save_raw_candles(config, "bitunix", "futures", "ETHUSDT", "4h", df)

    # "new" download overlaps the last stored candle (refreshed) and extends
    # by 10 newer candles
    newer = df.tail(11).copy()
    newer.index = newer.index + pd.Timedelta(days=100)
    newer = newer * 0.5  # different values; OHLC relations stay valid

    merged, _ = save_raw_candles(config, "bitunix", "futures", "ETHUSDT", "4h", newer)
    assert len(merged) == len(df) + 10
    # the refreshed tail carries the new values, not the stale stored ones
    assert merged["close"].iloc[-11] == newer["close"].iloc[0]
    assert merged.index.is_unique and merged.index.is_monotonic_increasing
    assert not np.allclose(merged["close"].iloc[-1], df["close"].iloc[-1])


def test_refresh_tail_only_when_new_data_reaches_tail(config: LabConfig) -> None:
    # backward extension: new data is strictly older - the current tail must
    # stay untouched even with refresh_tail > 0
    df = make_df()
    save_raw_candles(config, "bitunix", "futures", "ETHUSDT", "4h", df)
    older = df.head(5).copy()
    older.index = older.index - pd.Timedelta(days=100)
    older = older * 2.0

    merged, _ = save_raw_candles(config, "bitunix", "futures", "ETHUSDT", "4h", older)
    assert len(merged) == len(df) + 5
    assert merged["close"].iloc[-1] == df["close"].iloc[-1]  # tail untouched


def test_save_raw_tolerates_ohlc_anomalies_but_records_them(config: LabConfig) -> None:
    df = make_df()
    df.loc[df.index[10], "high"] = df.loc[df.index[10], "low"] - 1  # high < low
    merged, _ = save_raw_candles(config, "bitunix", "futures", "BTCUSDT", "4h", df)
    assert len(merged) == len(df)
    metadata = read_metadata(config.data_dir / "metadata" / "raw" / "bitunix" / "futures" / "BTCUSDT_4h.json")
    assert metadata["ohlc_anomalies"] >= 1


def test_save_raw_deduplicates_download_payload_idempotently(config: LabConfig) -> None:
    # re-downloading an overlapping range must be idempotent: duplicate rows
    # collapse onto the existing dataset (first wins) instead of corrupting it.
    df = make_df()
    duplicated = pd.concat([df, df.iloc[[5]]]).sort_index()
    merged, _ = save_raw_candles(config, "bitunix", "futures", "BTCUSDT", "4h", duplicated)
    assert len(merged) == len(df)
    assert merged.index.is_unique


def test_save_raw_rejects_empty(config: LabConfig) -> None:
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    with pytest.raises(StorageError, match="empty"):
        save_raw_candles(config, "bitunix", "futures", "BTCUSDT", "4h", empty)


def test_merge_raw_candles_handles_none_and_gaps() -> None:
    df = make_df(10)
    assert merge_raw_candles(None, df).equals(df)
    later = df.copy()
    later.index = later.index + pd.Timedelta(days=5)
    merged = merge_raw_candles(df, later)
    assert len(merged) == 20
    assert merged.index.is_monotonic_increasing


def test_save_and_load_processed(config: LabConfig) -> None:
    df = make_df()
    df["regime"] = "RANGE"
    path = save_processed(
        config, "regimes", exchange="bitunix", market="futures", symbol="SOLUSDT",
        timeframe="4h", df=df, raw_df=df, extra_metadata={"regime_config_fingerprint": "abc"},
    )
    assert path.name == "4h_regimes.parquet"
    assert path == config.data_dir / "processed" / "bitunix" / "futures" / "SOLUSDT" / "4h_regimes.parquet"
    loaded = load_processed(config, "regimes", "bitunix", "futures", "SOLUSDT", "4h")
    assert loaded is not None and len(loaded) == len(df)
    assert loaded["regime"].eq("RANGE").all()

    metadata = read_metadata(
        config.data_dir / "metadata" / "processed" / "bitunix" / "futures" / "SOLUSDT_4h_regimes.json"
    )
    assert metadata["artifact"] == "regimes"
    assert metadata["regime_config_fingerprint"] == "abc"
    assert metadata["exchange"] == "bitunix"
    assert metadata["market"] == "futures"
    assert metadata["symbol"] == "SOLUSDT"
    assert metadata["timeframe"] == "4h"
    # provenance / freshness fields
    source = metadata["source"]
    assert source["exchange"] == "bitunix"
    assert source["market"] == "futures"
    assert source["raw_rows"] == len(df)
    assert len(source["raw_content_hash"]) == 64
    assert metadata["code_version"]
    assert metadata["schema_version"] == "1.0"
    assert "source_rows_sha256" not in metadata  # placeholder removed


def test_raw_content_hash_is_deterministic_and_content_sensitive() -> None:
    from crypto_strategy_lab.data.models import raw_content_hash

    df = make_df()
    h1 = raw_content_hash(df)
    h2 = raw_content_hash(df.copy())
    assert h1 == h2
    changed = df.copy()
    changed.iloc[0, changed.columns.get_loc("close")] += 1e-9
    assert raw_content_hash(changed) != h1
    reordered = df.iloc[::-1]
    assert raw_content_hash(reordered) != h1  # shape/order changes flip the hash


def test_check_freshness_detects_raw_and_config_changes(config: LabConfig) -> None:
    from crypto_strategy_lab.data.storage import check_freshness, config_fingerprint

    df = make_df()
    labelled = df.copy()
    labelled["regime"] = "RANGE"
    fingerprint = config_fingerprint({"a": 1})
    save_processed(config, "regimes", exchange="bitunix", market="futures", symbol="BTCUSDT",
                   timeframe="4h", df=labelled, raw_df=df,
                   extra_metadata={"regime_config_fingerprint": fingerprint})

    fresh = check_freshness(config, "regimes", "bitunix", "futures", "BTCUSDT", "4h", df,
                            config_fingerprint=fingerprint)
    assert fresh.fresh

    # raw dataset changed -> stale
    modified = df.copy()
    modified.iloc[0, modified.columns.get_loc("close")] *= 2
    stale = check_freshness(config, "regimes", "bitunix", "futures", "BTCUSDT", "4h", modified,
                            config_fingerprint=fingerprint)
    assert not stale.fresh
    assert any("raw dataset changed" in r for r in stale.reasons)

    # regime config changed -> stale
    other_fp = check_freshness(config, "regimes", "bitunix", "futures", "BTCUSDT", "4h", df,
                               config_fingerprint="other")
    assert not other_fp.fresh
    assert any("configuration changed" in r for r in other_fp.reasons)


def test_spot_and_futures_raw_coexist(config: LabConfig) -> None:

    df = make_df()
    spot_df, _ = save_raw_candles(config, "bitunix", "spot", "BTCUSDT", "4h", df)
    futures_df, _ = save_raw_candles(config, "bitunix", "futures", "BTCUSDT", "4h", df * 2)
    # separate files, no cross-contamination
    assert spot_df.equals(df)
    assert futures_df.index.equals(df.index) and not futures_df["close"].equals(df["close"])
    assert raw_candles_path(config, "bitunix", "spot", "BTCUSDT", "4h").exists()
    assert raw_candles_path(config, "bitunix", "futures", "BTCUSDT", "4h").exists()
    spot_meta = read_metadata(
        config.data_dir / "metadata" / "raw" / "bitunix" / "spot" / "BTCUSDT_4h.json"
    )
    futures_meta = read_metadata(
        config.data_dir / "metadata" / "raw" / "bitunix" / "futures" / "BTCUSDT_4h.json"
    )
    assert spot_meta["market"] == "spot"
    assert futures_meta["market"] == "futures"
    assert spot_meta["raw_content_hash"] != futures_meta["raw_content_hash"]


def test_spot_and_futures_processed_coexist(config: LabConfig) -> None:
    df = make_df()
    for market, factor in (("spot", 1.0), ("futures", 2.0)):
        for artifact in ("indicators", "regimes"):
            frame = df.copy()
            frame["marker"] = market
            if artifact == "regimes":
                frame["regime"] = market.upper()
            save_processed(
                config, artifact, exchange="bitunix", market=market, symbol="BTCUSDT",
                timeframe="4h", df=frame, raw_df=df,
                extra_metadata={"regime_config_fingerprint": "fp"},
            )
    base = config.data_dir / "processed" / "bitunix"
    assert (base / "spot" / "BTCUSDT" / "4h_regimes.parquet").exists()
    assert (base / "futures" / "BTCUSDT" / "4h_regimes.parquet").exists()
    spot_regimes = load_processed(config, "regimes", "bitunix", "spot", "BTCUSDT", "4h")
    futures_regimes = load_processed(config, "regimes", "bitunix", "futures", "BTCUSDT", "4h")
    assert spot_regimes["regime"].eq("SPOT").all()
    assert futures_regimes["regime"].eq("FUTURES").all()
    spot_meta = read_metadata(
        config.data_dir / "metadata" / "processed" / "bitunix" / "spot" / "BTCUSDT_4h_regimes.json"
    )
    assert spot_meta["market"] == "spot"


def test_freshness_rejects_market_mismatch(config: LabConfig) -> None:
    from crypto_strategy_lab.data.storage import check_freshness, config_fingerprint

    df = make_df()
    fingerprint = config_fingerprint({"a": 1})
    save_processed(config, "regimes", exchange="bitunix", market="futures", symbol="BTCUSDT",
                   timeframe="4h", df=df, raw_df=df,
                   extra_metadata={"regime_config_fingerprint": fingerprint})
    # raw data exists for both markets (same content), but the artifact was
    # generated from futures and is requested for spot -> rejected
    for market in ("spot",):
        status = check_freshness(config, "regimes", "bitunix", market, "BTCUSDT", "4h", df,
                                 config_fingerprint=fingerprint)
        assert not status.fresh
        assert any("market" in r for r in status.reasons)


def test_freshness_rejects_legacy_marketless_metadata(config: LabConfig) -> None:
    import json

    from crypto_strategy_lab.data.storage import check_freshness, find_legacy_processed_artifacts

    df = make_df()
    fingerprint = config_fingerprint({"a": 1})

    # scenario 1: only legacy (pre-market-namespace) files exist
    legacy_meta_dir = config.data_dir / "metadata" / "processed"
    legacy_meta_dir.mkdir(parents=True, exist_ok=True)
    (legacy_meta_dir / "BTCUSDT_4h_regimes.json").write_text(json.dumps({
        "artifact": "regimes", "symbol": "BTCUSDT", "timeframe": "4h",
        "regime_config_fingerprint": fingerprint,
        "source": {"exchange": "bitunix", "raw_content_hash": "whatever"},
    }))
    (config.data_dir / "processed" / "BTCUSDT").mkdir(parents=True, exist_ok=True)
    df.to_parquet(config.data_dir / "processed" / "BTCUSDT" / "4h_regimes.parquet")

    status = check_freshness(config, "regimes", "bitunix", "spot", "BTCUSDT", "4h", df,
                             config_fingerprint=fingerprint)
    assert not status.fresh
    assert status.legacy
    assert any("legacy marketless artifact exists" in r for r in status.reasons)
    assert any("regenerate" in r for r in status.reasons)
    legacy_files = find_legacy_processed_artifacts(config, "BTCUSDT", "4h")
    assert legacy_files  # both parquet and json detected

    # scenario 2: namespaced metadata exists but lacks the market field
    save_processed(config, "regimes", exchange="bitunix", market="spot", symbol="BTCUSDT",
                   timeframe="4h", df=df, raw_df=df,
                   extra_metadata={"regime_config_fingerprint": fingerprint})
    meta_path = (
        config.data_dir / "metadata" / "processed" / "bitunix" / "spot" / "BTCUSDT_4h_regimes.json"
    )
    metadata = json.loads(meta_path.read_text())
    metadata.pop("market")
    (metadata.get("source") or {}).pop("market", None)
    meta_path.write_text(json.dumps(metadata))
    status = check_freshness(config, "regimes", "bitunix", "spot", "BTCUSDT", "4h", df,
                             config_fingerprint=fingerprint)
    assert not status.fresh
    assert status.legacy
    assert any("marketless legacy artifact" in r for r in status.reasons)


def test_load_missing_returns_none(config: LabConfig) -> None:
    assert load_raw_candles(config, "bitunix", "futures", "BTCUSDT", "4h") is None
    assert load_processed(config, "regimes", "bitunix", "futures", "BTCUSDT", "4h") is None
