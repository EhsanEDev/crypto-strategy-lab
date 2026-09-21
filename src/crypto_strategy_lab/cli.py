"""Command line interface for the research lab.

Commands::

    python -m crypto_strategy_lab download   --symbol BTCUSDT --timeframe 4h [--start ...] [--end ...]
    python -m crypto_strategy_lab indicators --symbol BTCUSDT --timeframe 4h
    python -m crypto_strategy_lab regime     --symbol BTCUSDT --timeframe 4h
    python -m crypto_strategy_lab report     --symbol BTCUSDT --timeframe 4h
    python -m crypto_strategy_lab pipeline   --symbol BTCUSDT --timeframe 4h
    python -m crypto_strategy_lab pipeline   --all

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
    help="crypto-strategy-lab: research lab for market data, indicators and regimes.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)

REGIME_TIMEFRAME_NOTE = "regime detection is defined for the configured regime timeframe"


def _resolve_symbol_timeframe(config: LabConfig, symbol: str, timeframe: str) -> tuple[str, str]:
    symbol = symbol.upper()
    timeframe = timeframe.lower()
    config.validate_symbols([symbol])
    if timeframe not in config.timeframes:
        raise typer.BadParameter(
            f"timeframe {timeframe!r} is not configured; allowed: {config.timeframes}"
        )
    return symbol, timeframe


@app.command()
def download(
    symbol: str = typer.Option(..., "--symbol", help="e.g. BTCUSDT"),
    timeframe: str = typer.Option("4h", "--timeframe", help="1h | 4h | 1d"),
    start: str | None = typer.Option(None, "--start", help="YYYY-MM-DD inclusive"),
    end: str | None = typer.Option(None, "--end", help="YYYY-MM-DD inclusive"),
    market: str | None = typer.Option(None, "--market", help="futures (default) | spot"),
    config_path: str | None = typer.Option(None, "--config"),
) -> None:
    """Download historical candles from Bitunix and store them as Parquet."""
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

    existing = load_raw(config, "bitunix", symbol, timeframe)
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
            typer.echo(f"[INFO] {symbol} {timeframe}: no new candles; already up to date")
            continue
        typer.echo(
            f"[INFO] Received {len(df):,} candles ({df.index.min()} → {df.index.max()})"
        )
        merged, path = save_raw_candles(
            config,
            exchange="bitunix",
            symbol=symbol,
            timeframe=timeframe,
            new_df=df,
            extra_metadata={"market": market},
        )
        typer.echo(f"[INFO] Validation passed ({len(merged):,} rows total)")
        typer.echo(f"[INFO] Saved {path}")


@app.command()
def indicators(
    symbol: str = typer.Option(..., "--symbol"),
    timeframe: str = typer.Option("4h", "--timeframe"),
    config_path: str | None = typer.Option(None, "--config"),
) -> None:
    """Compute v001 indicators for a stored dataset."""
    from .data.loader import load_raw_validated
    from .data.storage import config_fingerprint, save_processed
    from .indicators.registry import compute_indicators

    config = load_config(config_path)
    setup_logging(config.log_level)
    symbol, timeframe = _resolve_symbol_timeframe(config, symbol, timeframe)

    typer.secho(f"Calculating indicators for {symbol} {timeframe}", fg=typer.colors.CYAN)
    df = load_raw_validated(config, "bitunix", symbol, timeframe)
    result = compute_indicators(df, config.regime)
    fingerprint = config_fingerprint(config.regime.model_dump())
    save_processed(
        config,
        "indicators",
        symbol,
        timeframe,
        result,
        extra_metadata={"regime_config_fingerprint": fingerprint},
    )
    typer.echo(f"[INFO] Saved indicators for {symbol} {timeframe} ({len(result):,} rows)")


@app.command()
def regime(
    symbol: str = typer.Option(..., "--symbol"),
    timeframe: str | None = typer.Option(None, "--timeframe"),
    config_path: str | None = typer.Option(None, "--config"),
) -> None:
    """Detect regimes for a stored dataset (indicators are computed here)."""
    from .data.loader import load_raw_validated
    from .data.storage import config_fingerprint, save_processed
    from .regime.detector import detect_regime

    config = load_config(config_path)
    setup_logging(config.log_level)
    tf = (timeframe or config.regime_timeframe).lower()
    symbol, tf = _resolve_symbol_timeframe(config, symbol, tf)

    typer.secho(f"Detecting regimes for {symbol} {tf}", fg=typer.colors.CYAN)
    df = load_raw_validated(config, "bitunix", symbol, tf)
    labelled = detect_regime(df, config.regime)

    distribution = labelled["regime"].value_counts(normalize=True).mul(100).round(1)
    for label, share in distribution.items():
        typer.echo(f"[INFO] {label}: {share:.1f}%")

    fingerprint = config_fingerprint(config.regime.model_dump())
    save_processed(
        config,
        "regimes",
        symbol,
        tf,
        labelled,
        extra_metadata={"regime_config_fingerprint": fingerprint},
    )
    typer.echo(f"[INFO] Saved regimes for {symbol} {tf} ({len(labelled):,} rows)")


@app.command()
def report(
    symbol: str = typer.Option(..., "--symbol"),
    timeframe: str | None = typer.Option(None, "--timeframe"),
    config_path: str | None = typer.Option(None, "--config"),
) -> None:
    """Generate the markdown regime report from stored artifacts."""
    from .data.loader import load_raw_validated
    from .data.storage import load_processed

    config = load_config(config_path)
    setup_logging(config.log_level)
    tf = (timeframe or config.regime_timeframe).lower()
    symbol, tf = _resolve_symbol_timeframe(config, symbol, tf)

    raw = load_raw_validated(config, "bitunix", symbol, tf)
    regimes = load_processed(config, "regimes", symbol, tf)
    if regimes is None or regimes.empty:
        typer.secho(
            f"No regime dataset for {symbol} {tf}. Run: "
            f"python -m crypto_strategy_lab regime --symbol {symbol} --timeframe {tf}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    path = write_regime_report(config, symbol, tf, raw, regimes, config.regime)
    typer.echo(f"[INFO] Report written: {path}")


@app.command()
def pipeline(
    symbol: str = typer.Option(None, "--symbol", help="e.g. BTCUSDT"),
    timeframe: str | None = typer.Option(None, "--timeframe"),
    start: str | None = typer.Option(None, "--start"),
    end: str | None = typer.Option(None, "--end"),
    all_assets: bool = typer.Option(False, "--all", help="run for every configured asset"),
    skip_download: bool = typer.Option(False, "--skip-download"),
    config_path: str | None = typer.Option(None, "--config"),
) -> None:
    """Run the full milestone-1 pipeline: download → indicators → regime → report."""
    config = load_config(config_path)
    setup_logging(config.log_level)
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
            _run_pipeline_for_symbol(config, sym, timeframe, start, end, skip_download)
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
) -> None:
    from .data.loader import load_raw_validated
    from .data.storage import config_fingerprint, save_processed
    from .regime.detector import detect_regime
    from .regime.models import REGIME_PRIORITY

    tf = (timeframe or config.regime_timeframe).lower()
    if tf not in config.timeframes:
        raise typer.BadParameter(f"timeframe {tf!r} is not configured; allowed: {config.timeframes}")

    typer.secho(f"=== Pipeline {symbol} {tf} ===", fg=typer.colors.CYAN, bold=True)

    if not skip_download:
        for raw_tf in config.timeframes:
            _download_one(config, symbol, raw_tf, start, end)
    else:
        typer.echo("[INFO] Skipping download (--skip-download)")
    df = load_raw_validated(config, "bitunix", symbol, tf)
    typer.echo(f"[INFO] Dataset: {df.index.min()} → {df.index.max()} ({len(df):,} candles)")

    typer.echo("[INFO] Calculating indicators")
    labelled = detect_regime(df, config.regime)
    fingerprint = config_fingerprint(config.regime.model_dump())
    save_processed(
        config,
        "regimes",
        symbol,
        tf,
        labelled,
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
    write_regime_report(config, symbol, tf, df, labelled, config.regime, fingerprint)
    typer.echo(f"[INFO] Done: {symbol} {tf}")


@app.command("config")
def show_config(config_path: str | None = typer.Option(None, "--config")) -> None:
    """Print the resolved configuration."""
    import json

    config = load_config(config_path)
    typer.echo(json.dumps(config.model_dump(), indent=2, default=str))


if __name__ == "__main__":
    app()
