"""Strict (research-ready) validation mode tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_research.data.validator import is_research_ready, validate_ohlcv
from tests.helpers import make_ohlcv


def _clean(n: int = 60) -> pd.DataFrame:
    return make_ohlcv(100 * np.exp(np.cumsum(np.random.default_rng(5).normal(0, 0.01, n))))


def test_strict_mode_passes_clean_data() -> None:
    df = _clean()
    result = validate_ohlcv(df, "4h", strict=True)
    assert result.is_valid
    assert is_research_ready(df, "4h")


def test_strict_mode_flags_ohlc_anomalies_as_errors() -> None:
    df = _clean()
    df.loc[df.index[10], "high"] = df.loc[df.index[10], "low"] - 1  # high < low
    result = validate_ohlcv(df, "4h", strict=True)
    assert not result.is_valid
    assert result.ohlc_anomalies >= 1
    assert any("OHLC relation violation" in e for e in result.errors)
    # audit mode still tolerates (warning only) for raw preservation
    assert validate_ohlcv(df, "4h").is_valid


def test_strict_mode_flags_gaps_as_errors() -> None:
    close = pd.Series([100.0, 101.0, 103.0])
    index = pd.DatetimeIndex(["2024-01-01T00:00", "2024-01-01T04:00", "2024-01-01T12:00"], tz="UTC")
    df = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": [1.0] * 3},
        index=index,
    )
    strict = validate_ohlcv(df, "4h", strict=True)
    assert not strict.is_valid
    assert any("gap" in e for e in strict.errors)
    assert validate_ohlcv(df, "4h").is_valid  # audit mode: warning only


def test_strict_mode_flags_nan_and_infinite_values() -> None:
    df = _clean()
    df.loc[df.index[5], "volume"] = np.nan
    result = validate_ohlcv(df, "4h", strict=True)
    assert not result.is_valid
    assert result.non_finite_values >= 1
    assert any("NaN/infinite" in e for e in result.errors)

    df2 = _clean()
    df2.loc[df2.index[5], "close"] = np.inf
    result2 = validate_ohlcv(df2, "4h", strict=True)
    assert not result2.is_valid
    assert result2.non_finite_values >= 1


def test_strict_mode_flags_misaligned_timestamps() -> None:
    df = _clean()
    shifted = df.copy()
    shifted.index = shifted.index + pd.Timedelta(minutes=17)
    result = validate_ohlcv(shifted, "4h", strict=True)
    assert not result.is_valid
    assert result.misaligned_timestamps == len(shifted)
    assert any("not aligned" in e for e in result.errors)
    # the same shift also breaks the 1h grid (minutes are non-zero)
    hourly = validate_ohlcv(shifted, "1h", strict=True)
    assert hourly.misaligned_timestamps == len(shifted)
    # a daily dataset aligns on the 1d grid (midnight UTC)
    daily_df = make_ohlcv(
        100 * np.exp(np.cumsum(np.random.default_rng(6).normal(0, 0.01, 30))), freq="1d"
    )
    assert validate_ohlcv(daily_df, "1d", strict=True).is_valid


def test_strict_mode_flags_duplicates() -> None:
    df = _clean()
    duplicated = pd.concat([df, df.iloc[[5]]]).sort_index()
    result = validate_ohlcv(duplicated, "4h", strict=True)
    assert not result.is_valid
    assert result.duplicate_timestamps


def test_strict_mode_flags_non_positive_prices_and_volume() -> None:
    df = _clean()
    df.loc[df.index[3], "close"] = 0.0
    df.loc[df.index[4], "volume"] = -1.0
    result = validate_ohlcv(df, "4h", strict=True)
    assert not result.is_valid
    assert any("non-positive" in e for e in result.errors)
    assert any("negative volume" in e for e in result.errors)
