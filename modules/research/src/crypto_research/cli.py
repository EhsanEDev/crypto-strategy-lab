"""Command line interface for the research lab.

Commands::

    python -m crypto_research download   --symbol BTCUSDT --timeframe 4h [--start ...] [--end ...]
    python -m crypto_research indicators --symbol BTCUSDT --timeframe 4h
    python -m crypto_research regime     --symbol BTCUSDT --timeframe 4h
    python -m crypto_research report     --symbol BTCUSDT --timeframe 4h
    python -m crypto_research pipeline   --symbol BTCUSDT --timeframe 4h
    python -m crypto_research pipeline   --all

Date semantics (all UTC): ``--start YYYY-MM-DD`` begins at that day's
00:00 UTC; ``--end YYYY-MM-DD`` includes the whole UTC calendar day
(implemented internally as a next-day exclusive boundary). Timestamp
inputs are supported consistently (start inclusive instant, end inclusive
instant). In-progress candles are never persisted as history.

Regime timeframe defaults to the configured ``regime_timeframe`` (4h for
Milestone 1); any configured timeframe can be passed explicitly.

There is deliberately no order/trading command: this milestone is
research-only (see README Non-Goals).
"""

from __future__ import annotations

import pandas as pd
import typer

from .config import LabConfig, load_config
from .indicators.registry import warmup_bars
from .research.reports import write_regime_report
from .utils.logging import setup_logging

app = typer.Typer(
    help="crypto-research: market data, indicators and regime detection research.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)


def _resolve_symbol_timeframe(config: LabConfig, symbol: str, timeframe: str) -> tuple[str, str]:
    symbol = symbol.upper()
    timeframe = timeframe.lower()
    config.validate_symbols([symbol])
    if timeframe not in config.timeframes:
        raise typer.BadParameter(
            f"timeframe {timeframe!r} is not configured; allowed: {config.timeframes}"
        )
    return symbol, timeframe


def _resolve_market(config: LabConfig, market: str | None) -> str:
    market = (market or config.default_market).lower()
    if market not in ("spot", "futures"):
        raise typer.BadParameter(f"market must be 'spot' or 'futures', got {market!r}")
    return market


def _load_research_input(
    config: LabConfig, symbol: str, tf: str, allow_non_ready: bool, market: str | None = None
) -> pd.DataFrame:
    from .data.loader import DataNotReadyError, load_raw_validated
    from .data.storage import StorageError

    try:
        return load_raw_validated(
            config, "bitunix", market or config.default_market, symbol, tf,
            allow_non_ready=allow_non_ready,
        )
    except DataNotReadyError as exc:
        typer.secho(f"[ERROR] {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    except StorageError as exc:
        typer.secho(f"[ERROR] {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def download(
    symbol: str = typer.Option(..., "--symbol", help="e.g. BTCUSDT"),
    timeframe: str = typer.Option("4h", "--timeframe", help="1h | 4h | 1d"),
    start: str | None = typer.Option(None, "--start", help="YYYY-MM-DD or UTC timestamp (inclusive)"),
    end: str | None = typer.Option(None, "--end", help="YYYY-MM-DD or UTC timestamp (whole day included)"),
    market: str | None = typer.Option(None, "--market", help="futures (default) | spot (kline/history)"),
    config_path: str | None = typer.Option(None, "--config"),
) -> None:
    """Download historical CLOSED candles from Bitunix into Parquet.

    Incremental and idempotent: only missing ranges are fetched, the last
    stored candle is refreshed, and in-progress candles are never stored.
    """
    config = load_config(config_path)
    setup_logging(config.log_level)
    symbol, timeframe = _resolve_symbol_timeframe(config, symbol, timeframe)
    market = (market or config.default_market).lower()
    if market not in ("spot", "futures"):
        raise typer.BadParameter(f"market must be 'spot' or 'futures', got {market!r}")
    _download_one(config, symbol, timeframe, start, end, market=market)


def download_ranges(
    existing: pd.DataFrame | None, requested_start: str, requested_end: str | None
) -> list[tuple[str, str | None]]:
    """Missing date ranges for an incremental download (no full re-fetch).

    ``start``/``end`` are treated as calendar dates, so a range is only
    requested when it extends beyond the stored dataset by at least a day.
    """
    if existing is None or existing.empty:
        return [(requested_start, requested_end)]
    first, last = existing.index.min().normalize(), existing.index.max().normalize()
    ranges: list[tuple[str, str | None]] = []
    requested_end_ts = to_utc_ts(requested_end).normalize() if requested_end else None
    if requested_end_ts is None or last < requested_end_ts:
        ranges.append((str(last), requested_end))  # extend forward
    if to_utc_ts(requested_start).normalize() < first:
        ranges.append((requested_start, str(first)))  # extend backward
    return ranges


def to_utc_ts(value: str) -> pd.Timestamp:
    from .data.models import to_utc_timestamp

    return to_utc_timestamp(value)


def _download_one(
    config: LabConfig,
    symbol: str,
    timeframe: str,
    start: str | None,
    end: str | None,
    market: str | None = None,
) -> None:
    from .data.exchanges.bitunix import BitunixDataProvider
    from .data.loader import load_raw
    from .data.storage import save_raw_candles

    market = (market or config.default_market).lower()
    requested_start = start or config.default_start

    existing = load_raw(config, "bitunix", market, symbol, timeframe)
    ranges = download_ranges(existing, requested_start, end)
    if not ranges:
        typer.echo(f"[INFO] {symbol} {timeframe}: already up to date (last candle {existing.index.max()})")
        return

    for range_start, range_end in ranges:
        typer.secho(
            f"Downloading {symbol} {timeframe} from Bitunix ({market}) "
            f"for {range_start} → {range_end or 'latest'}",
            fg=typer.colors.CYAN,
        )
        with BitunixDataProvider(config.exchange, market=market) as provider:
            df = provider.fetch_klines(
                symbol, timeframe, start=range_start, end=range_end, allow_empty=True
            )
        if df.empty:
            typer.echo(f"[INFO] {symbol} {timeframe}: no new closed candles; already up to date")
            continue
        typer.echo(
            f"[INFO] Received {len(df):,} closed candles ({df.index.min()} → {df.index.max()})"
        )
        merged, path = save_raw_candles(
            config,
            exchange="bitunix",
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            new_df=df,
        )
        typer.echo(f"[INFO] Validation passed ({len(merged):,} rows total)")
        typer.echo(f"[INFO] Saved {path}")


@app.command()
def indicators(
    symbol: str = typer.Option(..., "--symbol"),
    timeframe: str = typer.Option("4h", "--timeframe"),
    market: str | None = typer.Option(None, "--market", help="futures (default) | spot"),
    allow_non_ready: bool = typer.Option(
        False, "--allow-non-ready", help="explicit override: proceed on imperfect data"
    ),
    config_path: str | None = typer.Option(None, "--config"),
) -> None:
    """Compute v001 indicators for a stored dataset (quality gate enforced)."""
    from .data.storage import config_fingerprint, save_processed
    from .indicators.registry import compute_indicators

    config = load_config(config_path)
    setup_logging(config.log_level)
    symbol, timeframe = _resolve_symbol_timeframe(config, symbol, timeframe)
    market = _resolve_market(config, market)

    typer.secho(f"Calculating indicators for {symbol} {timeframe} ({market})", fg=typer.colors.CYAN)
    df = _load_research_input(config, symbol, timeframe, allow_non_ready, market)
    result = compute_indicators(df, config.regime)
    fingerprint = config_fingerprint(config.regime.model_dump())
    save_processed(
        config,
        "indicators",
        exchange="bitunix",
        market=market,
        symbol=symbol,
        timeframe=timeframe,
        df=result,
        raw_df=df,
        extra_metadata={"regime_config_fingerprint": fingerprint},
    )
    typer.echo(f"[INFO] Saved indicators for {symbol} {timeframe} ({market}) ({len(result):,} rows)")


@app.command()
def regime(
    symbol: str = typer.Option(..., "--symbol"),
    timeframe: str | None = typer.Option(None, "--timeframe"),
    market: str | None = typer.Option(None, "--market", help="futures (default) | spot"),
    allow_non_ready: bool = typer.Option(
        False, "--allow-non-ready", help="explicit override: proceed on imperfect data"
    ),
    config_path: str | None = typer.Option(None, "--config"),
) -> None:
    """Detect regimes for a stored dataset (quality gate enforced)."""
    from .data.storage import config_fingerprint, save_processed
    from .regime.detector import detect_regime

    config = load_config(config_path)
    setup_logging(config.log_level)
    tf = (timeframe or config.regime_timeframe).lower()
    symbol, tf = _resolve_symbol_timeframe(config, symbol, tf)
    market = _resolve_market(config, market)

    typer.secho(f"Detecting regimes for {symbol} {tf} ({market})", fg=typer.colors.CYAN)
    df = _load_research_input(config, symbol, tf, allow_non_ready, market)
    labelled = detect_regime(df, config.regime)

    distribution = labelled["regime"].value_counts(normalize=True).mul(100).round(1)
    for label, share in distribution.items():
        typer.echo(f"[INFO] {label}: {share:.1f}%")

    fingerprint = config_fingerprint(config.regime.model_dump())
    save_processed(
        config,
        "regimes",
        exchange="bitunix",
        market=market,
        symbol=symbol,
        timeframe=tf,
        df=labelled,
        raw_df=df,
        extra_metadata={"regime_config_fingerprint": fingerprint},
    )
    typer.echo(f"[INFO] Saved regimes for {symbol} {tf} ({market}) ({len(labelled):,} rows)")


@app.command()
def report(
    symbol: str = typer.Option(..., "--symbol"),
    timeframe: str | None = typer.Option(None, "--timeframe"),
    market: str | None = typer.Option(None, "--market", help="futures (default) | spot"),
    allow_non_ready: bool = typer.Option(
        False, "--allow-non-ready", help="explicit override: proceed on imperfect data"
    ),
    config_path: str | None = typer.Option(None, "--config"),
) -> None:
    """Generate the markdown regime report from stored artifacts.

    Refuses stale artifacts: if the stored regimes were generated from a
    different raw dataset, a different market, or a different regime
    configuration, regenerate them first
    (``python -m crypto_research regime --symbol ... --market ...``).
    """
    from .data.storage import (
        check_freshness,
        config_fingerprint,
        load_processed,
        load_processed_metadata,
    )

    config = load_config(config_path)
    setup_logging(config.log_level)
    tf = (timeframe or config.regime_timeframe).lower()
    symbol, tf = _resolve_symbol_timeframe(config, symbol, tf)
    market = _resolve_market(config, market)

    raw = _load_research_input(config, symbol, tf, allow_non_ready, market)
    regimes = load_processed(config, "regimes", "bitunix", market, symbol, tf)
    if regimes is None or regimes.empty:
        typer.secho(
            f"No regime dataset for {symbol} {tf} ({market}). Run: "
            f"python -m crypto_research regime --symbol {symbol} --timeframe {tf} "
            f"--market {market}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    fingerprint = config_fingerprint(config.regime.model_dump())
    freshness = check_freshness(
        config, "regimes", "bitunix", market, symbol, tf, raw, config_fingerprint=fingerprint
    )
    if not freshness.fresh:
        typer.secho(
            f"Regime artifact for {symbol} {tf} ({market}) is stale: {freshness.describe()}. "
            f"Regenerate it with: python -m crypto_research regime --symbol {symbol} "
            f"--timeframe {tf} --market {market}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    regimes_metadata = load_processed_metadata(
        config, "regimes", "bitunix", market, symbol, tf
    )
    path = write_regime_report(
        config,
        symbol,
        tf,
        raw,
        regimes,
        market,
        regime_config=config.regime,
        fingerprint=fingerprint,
        regimes_metadata=regimes_metadata,
        freshness=freshness,
    )
    typer.echo(f"[INFO] Report written: {path}")


@app.command()
def pipeline(
    symbol: str = typer.Option(None, "--symbol", help="e.g. BTCUSDT"),
    timeframe: str | None = typer.Option(None, "--timeframe"),
    start: str | None = typer.Option(None, "--start"),
    end: str | None = typer.Option(None, "--end"),
    all_assets: bool = typer.Option(False, "--all", help="run for every configured asset"),
    skip_download: bool = typer.Option(False, "--skip-download"),
    market: str | None = typer.Option(None, "--market", help="futures (default) | spot"),
    allow_non_ready: bool = typer.Option(
        False, "--allow-non-ready", help="explicit override: proceed on imperfect data"
    ),
    config_path: str | None = typer.Option(None, "--config"),
) -> None:
    """Run the full milestone-1 pipeline: download → indicators → regime → report.

    Persists BOTH artifacts (``{tf}_indicators.parquet`` and
    ``{tf}_regimes.parquet``) under the selected market namespace and
    regenerates them, so they are always fresh. Spot and Futures artifacts
    never overwrite one another. Real Bitunix data usually contains
    exchange-reported OHLC anomalies; without ``--allow-non-ready`` the
    quality gate stops the pipeline before indicators/regimes/reports.
    """
    config = load_config(config_path)
    setup_logging(config.log_level)
    market = _resolve_market(config, market)
    if all_assets:
        symbols = list(config.assets)
    else:
        if symbol is None:
            raise typer.BadParameter("either --symbol or --all is required")
        symbols = [symbol.upper()]
        config.validate_symbols(symbols)

    exit_code = 0
    for sym in symbols:
        try:
            _run_pipeline_for_symbol(
                config, sym, timeframe, start, end, skip_download, allow_non_ready, market
            )
        except Exception as exc:  # keep other assets going, report failure
            typer.secho(f"[ERROR] {sym}: {exc}", fg=typer.colors.RED, err=True)
            exit_code = 1
    raise typer.Exit(code=exit_code)


def _run_pipeline_for_symbol(
    config: LabConfig,
    symbol: str,
    timeframe: str | None,
    start: str | None,
    end: str | None,
    skip_download: bool,
    allow_non_ready: bool,
    market: str | None = None,
) -> None:
    from .data.storage import config_fingerprint, save_processed
    from .regime.detector import detect_regime
    from .regime.models import REGIME_PRIORITY

    tf = (timeframe or config.regime_timeframe).lower()
    if tf not in config.timeframes:
        raise typer.BadParameter(f"timeframe {tf!r} is not configured; allowed: {config.timeframes}")
    market = _resolve_market(config, market)

    typer.secho(f"=== Pipeline {symbol} {tf} ({market}) ===", fg=typer.colors.CYAN, bold=True)

    if not skip_download:
        for raw_tf in config.timeframes:
            _download_one(config, symbol, raw_tf, start, end, market=market)
    else:
        typer.echo("[INFO] Skipping download (--skip-download)")

    df = _load_research_input(config, symbol, tf, allow_non_ready, market)
    typer.echo(f"[INFO] Dataset: {df.index.min()} → {df.index.max()} ({len(df):,} closed candles)")

    typer.echo("[INFO] Calculating indicators")
    labelled = detect_regime(df, config.regime)
    fingerprint = config_fingerprint(config.regime.model_dump())
    save_processed(
        config,
        "indicators",
        exchange="bitunix",
        market=market,
        symbol=symbol,
        timeframe=tf,
        df=labelled.drop(
            columns=["regime", "trend_condition", "volatility_condition", "range_condition",
                     "regime_reason", "regime_flags"],
            errors="ignore",
        ),
        raw_df=df,
        extra_metadata={"regime_config_fingerprint": fingerprint},
    )
    save_processed(
        config,
        "regimes",
        exchange="bitunix",
        market=market,
        symbol=symbol,
        timeframe=tf,
        df=labelled,
        raw_df=df,
        extra_metadata={"regime_config_fingerprint": fingerprint},
    )

    typer.echo("[INFO] Detecting regimes")
    distribution = labelled["regime"].value_counts(normalize=True).mul(100)
    for label in REGIME_PRIORITY:
        share = distribution.get(label.value, 0.0)
        typer.echo(f"[INFO] {label.value}: {share:.1f}%")

    typer.echo(
        f"[INFO] Indicator warm-up: first {warmup_bars(config.regime)} bars are UNCERTAIN by design"
    )
    from .data.storage import check_freshness, load_processed_metadata

    regimes_metadata = load_processed_metadata(config, "regimes", "bitunix", market, symbol, tf)
    freshness = check_freshness(
        config, "regimes", "bitunix", market, symbol, tf, df, config_fingerprint=fingerprint
    )
    if not freshness.fresh:  # paranoia: artifacts were just regenerated
        typer.secho(
            f"[ERROR] freshly generated artifact failed freshness: {freshness.describe()}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    write_regime_report(
        config,
        symbol,
        tf,
        df,
        labelled,
        market,
        regime_config=config.regime,
        fingerprint=fingerprint,
        regimes_metadata=regimes_metadata,
        freshness=freshness,
    )
    typer.echo(f"[INFO] Done: {symbol} {tf} ({market})")


@app.command("config")
def show_config(config_path: str | None = typer.Option(None, "--config")) -> None:
    """Print the resolved configuration."""
    import json

    config = load_config(config_path)
    typer.echo(json.dumps(config.model_dump(), indent=2, default=str))


if __name__ == "__main__":
    app()
