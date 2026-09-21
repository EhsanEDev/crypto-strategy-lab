"""Loading helpers used by CLI commands and research code.

Loading is intentionally separated from fetching: research code never
downloads, download code never computes.
"""

from __future__ import annotations

import pandas as pd

from ..config import LabConfig
from .models import to_utc_timestamp
from .validator import validate_ohlcv


def load_raw(config: LabConfig, exchange: str, symbol: str, timeframe: str) -> pd.DataFrame | None:
    """Load raw candles from parquet (or ``None`` when not downloaded yet)."""
    from .storage import load_raw_candles

    return load_raw_candles(config, exchange, symbol, timeframe)


def load_raw_validated(
    config: LabConfig, exchange: str, symbol: str, timeframe: str
) -> pd.DataFrame:
    """Load raw candles and validate them; raises ``StorageError`` if missing."""
    from .storage import StorageError, load_raw_candles

    df = load_raw_candles(config, exchange, symbol, timeframe)
    if df is None or df.empty:
        raise StorageError(
            f"no raw dataset for {symbol} {timeframe} ({exchange}). "
            f"Run: python -m crypto_strategy_lab download --symbol {symbol} --timeframe {timeframe}"
        )
    result = validate_ohlcv(df, timeframe)
    if not result.is_valid:
        raise StorageError(
            f"stored dataset for {symbol} {timeframe} failed validation: {result.summary()}"
        )
    return df


def slice_by_dates(
    df: pd.DataFrame, start: str | None, end: str | None
) -> pd.DataFrame:
    """Inclusive slice of a timestamp-indexed frame."""
    if start is not None:
        df = df[df.index >= to_utc_timestamp(start)]
    if end is not None:
        df = df[df.index <= to_utc_timestamp(end)]
    return df
