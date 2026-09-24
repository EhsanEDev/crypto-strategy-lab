"""Unit tests for data validation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from crypto_research.data.validator import validate_ohlcv
from tests.helpers import make_ohlcv


def _daily_df(**overrides: list[float] | pd.Series) -> pd.DataFrame:
    close = pd.Series([100.0, 101.0, 102.0])
    index = pd.date_range("2024-01-01", periods=3, freq="4h", tz="UTC")
    data = {
        "open": close.to_numpy(),
        "high": [101.0, 102.0, 103.0],
        "low": [99.0, 100.0, 101.0],
        "close": close.to_numpy(),
        "volume": [1.0] * 3,
    }
    data.update(overrides)
    return pd.DataFrame(data, index=index)


@pytest.fixture
def valid_df() -> pd.DataFrame:
    close = 100 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.01, 50)))
    return make_ohlcv(close)


def test_valid_dataset_passes(valid_df: pd.DataFrame) -> None:
    result = validate_ohlcv(valid_df, "4h")
    assert result.is_valid
    assert result.errors == []


def test_missing_columns_fails() -> None:
    close = pd.Series([100.0, 101.0, 102.0])
    df = pd.DataFrame({"open": close, "close": close}, index=pd.date_range("2024-01-01", periods=3, tz="UTC"))
    result = validate_ohlcv(df, "4h")
    assert not result.is_valid
    assert any("missing required columns" in e for e in result.errors)


def test_high_below_close_flagged_as_anomaly() -> None:
    result = validate_ohlcv(_daily_df(high=[99.0, 100.0, 101.0]), "4h")
    # OHLC relation violations are exchange-side quirks: quantified warnings,
    # not hard failures (real Bitunix data contains a handful of these).
    assert result.is_valid
    assert result.ohlc_anomalies == 3
    assert any("high >= max(open, close)" in w for w in result.warnings)


def test_low_above_open_flagged_as_anomaly() -> None:
    result = validate_ohlcv(_daily_df(low=[101.5, 102.5, 103.5]), "4h")
    assert result.is_valid
    assert result.ohlc_anomalies == 6
    assert any("low <= min(open, close)" in w for w in result.warnings)


def test_high_below_low_flagged_as_anomaly() -> None:
    result = validate_ohlcv(_daily_df(high=[90.0, 91.0, 92.0], low=[95.0, 96.0, 97.0]), "4h")
    assert result.is_valid
    assert result.ohlc_anomalies == 6
    assert any("high >= low" in w for w in result.warnings)


def test_non_positive_prices_fail() -> None:
    result = validate_ohlcv(_daily_df(high=[100.0, 101.0, 102.0], low=[99.0, 0.0, 101.0]), "4h")
    assert not result.is_valid
    assert any("non-positive" in e for e in result.errors)


def test_negative_volume_fails() -> None:
    result = validate_ohlcv(_daily_df(volume=[1.0, -5.0, 2.0]), "4h")
    assert not result.is_valid
    assert any("negative volume" in e for e in result.errors)


def test_duplicate_timestamps_fail() -> None:
    close = np.array([100.0, 101.0, 102.0, 103.0])
    index = pd.DatetimeIndex(["2024-01-01T00:00", "2024-01-01T04:00", "2024-01-01T04:00", "2024-01-01T08:00"], tz="UTC")
    df = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": [1.0] * 4},
        index=index,
    )
    result = validate_ohlcv(df, "4h")
    assert not result.is_valid
    assert len(result.duplicate_timestamps) == 1
    assert any("duplicate timestamps" in e for e in result.errors)


def test_unsorted_fail() -> None:
    close = np.array([100.0, 101.0, 102.0])
    index = pd.DatetimeIndex(["2024-01-01T08:00", "2024-01-01T00:00", "2024-01-01T04:00"], tz="UTC")
    df = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": [1.0] * 3},
        index=index,
    )
    result = validate_ohlcv(df, "4h")
    assert not result.is_valid
    assert any("not sorted ascending" in e for e in result.errors)


def test_naive_timestamps_fail() -> None:
    close = np.array([100.0, 101.0, 102.0])
    index = pd.DatetimeIndex(["2024-01-01T00:00", "2024-01-01T04:00", "2024-01-01T08:00"])  # naive
    df = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": [1.0] * 3},
        index=index,
    )
    result = validate_ohlcv(df, "4h")
    assert not result.is_valid
    assert any("timezone-aware" in e for e in result.errors)


def test_gap_detection_reports_without_filling() -> None:
    close = np.array([100.0, 101.0, 103.0])
    index = pd.DatetimeIndex(["2024-01-01T00:00", "2024-01-01T04:00", "2024-01-01T12:00"], tz="UTC")
    df = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": [1.0] * 3},
        index=index,
    )
    result = validate_ohlcv(df, "4h")
    assert result.is_valid  # gaps are warnings, not errors
    assert len(result.gaps) == 1
    gap_start, gap_end = result.gaps[0]
    assert gap_end - gap_start == pd.Timedelta(hours=8)
    assert any("gap" in w for w in result.warnings)


def test_no_gap_when_contiguous() -> None:
    result = validate_ohlcv(_daily_df(), "4h")
    assert result.is_valid
    assert result.gaps == []


def test_empty_dataset_fails() -> None:
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    result = validate_ohlcv(df, "4h")
    assert not result.is_valid
    assert any("empty" in e for e in result.errors)
