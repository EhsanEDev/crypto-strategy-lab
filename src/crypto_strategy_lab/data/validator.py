"""Data validation and quality gates.

Everything here is pure: ``validate_ohlcv`` takes a DataFrame and returns a
result, it never talks to the network, disk or CLI.

Two modes:

* **default (audit) mode** - used when *storing* raw downloads. Structural
  problems (duplicates, unsorted/non-UTC timestamps, missing columns,
  non-positive prices, negative volume, empty data) are hard errors. Gaps
  and exchange-reported OHLC inconsistencies are quantified warnings: raw
  observations are preserved for auditability and never silently repaired.

* **strict (research-ready) mode** - the quality gate for indicators,
  regime generation, reports and future backtests. *Everything* above is an
  error, plus: gaps, OHLC relation violations, non-timeframe-aligned
  timestamps, and NaN/infinite numeric values. Research code must not run
  on data that fails this mode unless the caller explicitly overrides
  (documented ``--allow-non-ready`` CLI flag).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .models import parse_timeframe

NUMERIC_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass
class ValidationResult:
    """Outcome of validating one OHLCV dataset."""

    is_valid: bool = True
    strict: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duplicate_timestamps: list[pd.Timestamp] = field(default_factory=list)
    gaps: list[tuple[pd.Timestamp, pd.Timestamp]] = field(default_factory=list)
    # OHLC relations (high >= max(open, close), ...) that the exchange itself
    # reported inconsistently. Quantified, never silently repaired.
    ohlc_anomalies: int = 0
    # strict-mode extras
    misaligned_timestamps: int = 0
    non_finite_values: int = 0

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def summary(self) -> str:
        status = "PASSED" if self.is_valid else "FAILED"
        mode = "strict" if self.strict else "audit"
        return (
            f"Validation {status} ({mode}): {len(self.errors)} errors, "
            f"{len(self.warnings)} warnings, "
            f"{len(self.duplicate_timestamps)} duplicates, "
            f"{len(self.gaps)} gaps, "
            f"{self.ohlc_anomalies} OHLC anomalies, "
            f"{self.misaligned_timestamps} misaligned, "
            f"{self.non_finite_values} non-finite"
        )


def validate_ohlcv(df: pd.DataFrame, timeframe: str, strict: bool = False) -> ValidationResult:
    """Validate a canonical OHLCV frame (index = timestamp, UTC).

    ``strict=True`` escalates every data-quality issue to a hard error and
    adds alignment/finiteness checks (research-ready gate).
    """
    result = ValidationResult(strict=strict)
    if df.empty:
        result.errors.append("dataset is empty")
        result.is_valid = False
        return result

    _check_columns(df, result)
    if not result.is_valid:
        return result

    _check_timestamps(df, result)
    _check_positive_values(df, result)
    _check_ohlc_validity(df, result)
    _check_continuity(df, timeframe, result)
    if strict:
        _check_alignment(df, timeframe, result)
        _check_finite(df, result)
        _escalate_warnings_to_errors(result)

    result.is_valid = not result.errors
    return result


def _fail(result: ValidationResult, message: str) -> None:
    result.errors.append(message)
    result.is_valid = False


def _check_columns(df: pd.DataFrame, result: ValidationResult) -> None:
    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        _fail(result, f"missing required columns: {missing}")


def _check_timestamps(df: pd.DataFrame, result: ValidationResult) -> None:
    index = df.index
    if not isinstance(index, pd.DatetimeIndex):
        _fail(result, "index must be a DatetimeIndex")
        return
    if index.tz is None:
        _fail(result, "timestamps must be timezone-aware (UTC)")
        return

    dup_mask = index.duplicated(keep="first")
    if dup_mask.any():
        dups = index[dup_mask].tolist()
        result.duplicate_timestamps = dups
        _fail(
            result,
            f"duplicate timestamps found: {dups[:5]}{' ...' if len(dups) > 5 else ''}",
        )

    if not index.is_monotonic_increasing:
        _fail(result, "timestamps are not sorted ascending")

    non_utc = index.tz is not None and str(index.tz) not in ("UTC", "utc", "Z", "GMT")
    if non_utc:
        _fail(result, f"timestamps must be UTC, got tz {index.tz}")


def _check_positive_values(df: pd.DataFrame, result: ValidationResult) -> None:
    for col in ("open", "high", "low", "close"):
        bad = df.index[df[col] <= 0]
        if len(bad):
            _fail(result, f"{len(bad)} candle(s) have non-positive {col}, e.g. {bad[:3].tolist()}")
    bad_vol = df.index[df["volume"] < 0]
    if len(bad_vol):
        _fail(result, f"{len(bad_vol)} candle(s) have negative volume, e.g. {bad_vol[:3].tolist()}")


def _check_ohlc_validity(df: pd.DataFrame, result: ValidationResult) -> None:
    """OHLC relation checks: quantified warnings in audit mode, errors in strict."""
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


def _check_continuity(df: pd.DataFrame, timeframe: str, result: ValidationResult) -> None:
    """Detect unexpected gaps between consecutive candles.

    Gaps are warnings in audit mode (never filled), errors in strict mode.
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


def _check_alignment(df: pd.DataFrame, timeframe: str, result: ValidationResult) -> None:
    """Strict mode: candle open times must align to the timeframe grid (UTC)."""
    tf = parse_timeframe(timeframe)
    seconds_since_midnight = (df.index - df.index.normalize()).total_seconds()
    misaligned = seconds_since_midnight % tf.seconds != 0
    if misaligned.any():
        bad = df.index[misaligned]
        result.misaligned_timestamps = len(bad)
        _fail(
            result,
            f"{len(bad)} candle(s) are not aligned to the {timeframe} grid, e.g. {bad[:3].tolist()}",
        )


def _check_finite(df: pd.DataFrame, result: ValidationResult) -> None:
    """Strict mode: no NaN or infinite values in numeric columns."""
    total = 0
    for col in NUMERIC_COLUMNS:
        values = df[col].to_numpy(dtype="float64")
        total += int((~np.isfinite(values)).sum())
    if total:
        result.non_finite_values = total
        _fail(result, f"{total} NaN/infinite value(s) in numeric OHLCV columns")


def _escalate_warnings_to_errors(result: ValidationResult) -> None:
    if result.gaps:
        _fail(result, f"{len(result.gaps)} candle gap(s) detected (strict mode)")
    if result.ohlc_anomalies:
        _fail(result, f"{result.ohlc_anomalies} OHLC relation violation(s) (strict mode)")


def is_research_ready(df: pd.DataFrame, timeframe: str) -> bool:
    """True when the dataset passes the strict (research-ready) gate."""
    return validate_ohlcv(df, timeframe, strict=True).is_valid
