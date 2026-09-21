"""Data validation and normalisation checks.

Everything here is pure: ``validate_ohlcv`` takes a DataFrame and returns a
result, it never talks to the network, disk or CLI.

Checks performed:

* OHLC validity      - ``high >= max(open, close)``, ``low <= min(open, close)``, ``high >= low``
* Positive values    - ``open/high/low/close > 0``, ``volume >= 0``
* Timestamps         - tz-aware UTC, strictly ascending, no unexpected duplicates
* Candle continuity  - unexpected gaps for fixed timeframes are *reported*,
  never forward-filled (gaps are a data-quality signal, not noise to hide).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .models import parse_timeframe


@dataclass
class ValidationResult:
    """Outcome of validating one OHLCV dataset."""

    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duplicate_timestamps: list[pd.Timestamp] = field(default_factory=list)
    gaps: list[tuple[pd.Timestamp, pd.Timestamp]] = field(default_factory=list)
    # OHLC relations (high >= max(open, close), ...) that the exchange itself
    # reported inconsistently. Quantified, not silently repaired and not a
    # hard failure: Bitunix serves a handful of such candles per multi-year
    # dataset. Structural problems (duplicates, sorting, non-positive
    # prices, ...) remain hard errors.
    ohlc_anomalies: int = 0

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def summary(self) -> str:
        status = "PASSED" if self.is_valid else "FAILED"
        return (
            f"Validation {status}: {len(self.errors)} errors, "
            f"{len(self.warnings)} warnings, "
            f"{len(self.duplicate_timestamps)} duplicates, "
            f"{len(self.gaps)} gaps, "
            f"{self.ohlc_anomalies} OHLC anomalies"
        )


def validate_ohlcv(df: pd.DataFrame, timeframe: str) -> ValidationResult:
    """Validate a canonical OHLCV frame (index = timestamp, UTC)."""
    result = ValidationResult()
    if df.empty:
        result.errors.append("dataset is empty")
        result.is_valid = False
        return result

    _check_columns(df, result)
    if not result.is_valid:
        return result

    _check_timestamps(df, result)
    _check_ohlc_validity(df, result)
    _check_positive_values(df, result)
    _check_continuity(df, timeframe, result)

    result.is_valid = not result.errors
    return result


def _check_columns(df: pd.DataFrame, result: ValidationResult) -> None:
    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        result.errors.append(f"missing required columns: {missing}")
        result.is_valid = False


def _check_timestamps(df: pd.DataFrame, result: ValidationResult) -> None:
    index = df.index
    if not isinstance(index, pd.DatetimeIndex):
        result.errors.append("index must be a DatetimeIndex")
        result.is_valid = False
        return
    if index.tz is None:
        result.errors.append("timestamps must be timezone-aware (UTC)")
        result.is_valid = False
        return

    dup_mask = index.duplicated(keep="first")
    if dup_mask.any():
        dups = index[dup_mask].tolist()
        result.duplicate_timestamps = dups
        result.errors.append(
            f"duplicate timestamps found: {dups[:5]}{' ...' if len(dups) > 5 else ''}"
        )
        result.is_valid = False

    if not index.is_monotonic_increasing:
        result.errors.append("timestamps are not sorted ascending")
        result.is_valid = False

    non_utc = index.tz is not None and str(index.tz) not in ("UTC", "utc", "Z", "GMT")
    if non_utc:
        result.errors.append(f"timestamps must be UTC, got tz {index.tz}")
        result.is_valid = False


def _check_ohlc_validity(df: pd.DataFrame, result: ValidationResult) -> None:
    """OHLC relation checks: quantified as warnings (exchange-side quirks)."""
    high, low = df["high"], df["low"]
    open_, close = df["open"], df["close"]

    bad_high = df.index[high < pd.concat([open_, close], axis=1).max(axis=1)]
    if len(bad_high):
        result.ohlc_anomalies += len(bad_high)
        result.warnings.append(
            f"{len(bad_high)} candle(s) violate high >= max(open, close), e.g. {bad_high[:3].tolist()}"
        )

    bad_low = df.index[low > pd.concat([open_, close], axis=1).min(axis=1)]
    if len(bad_low):
        result.ohlc_anomalies += len(bad_low)
        result.warnings.append(
            f"{len(bad_low)} candle(s) violate low <= min(open, close), e.g. {bad_low[:3].tolist()}"
        )

    bad_range = df.index[high < low]
    if len(bad_range):
        result.ohlc_anomalies += len(bad_range)
        result.warnings.append(
            f"{len(bad_range)} candle(s) violate high >= low, e.g. {bad_range[:3].tolist()}"
        )


def _check_positive_values(df: pd.DataFrame, result: ValidationResult) -> None:
    for col in ("open", "high", "low", "close"):
        bad = df.index[df[col] <= 0]
        if len(bad):
            result.errors.append(
                f"{len(bad)} candle(s) have non-positive {col}, e.g. {bad[:3].tolist()}"
            )
            result.is_valid = False
    bad_vol = df.index[df["volume"] < 0]
    if len(bad_vol):
        result.errors.append(
            f"{len(bad_vol)} candle(s) have negative volume, e.g. {bad_vol[:3].tolist()}"
        )
        result.is_valid = False


def _check_continuity(df: pd.DataFrame, timeframe: str, result: ValidationResult) -> None:
    """Detect unexpected gaps between consecutive candles.

    Gaps are warnings (not errors) and are never filled: callers decide
    what to do with them.
    """
    tf = parse_timeframe(timeframe)
    index = df.index
    if len(index) < 2:
        return
    step_seconds = index.to_series().diff().dt.total_seconds().iloc[1:]
    gap_mask = step_seconds > tf.seconds
    for end_ts in step_seconds[gap_mask].index:
        start_ts = end_ts - pd.Timedelta(seconds=float(step_seconds.loc[end_ts]))
        n_missing = int((pd.Timestamp(end_ts) - pd.Timestamp(start_ts)).total_seconds() // tf.seconds) - 1
        result.gaps.append((pd.Timestamp(start_ts), pd.Timestamp(end_ts)))
        result.warnings.append(
            f"gap between {pd.Timestamp(start_ts)} and {pd.Timestamp(end_ts)} "
            f"({n_missing} missing candle(s))"
        )
