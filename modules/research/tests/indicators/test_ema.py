"""EMA tests against hand-computed expected values."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from crypto_research.indicators.ema import ema


def test_ema_period_3_hand_computed() -> None:
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    result = ema(series, 3)
    # seed = mean(1,2,3) = 2 at index 2; alpha = 2/(3+1) = 0.5
    # idx3 = 2 + 0.5*(4-2) = 3.0  -- wait: value at idx3 is 4 -> 2+0.5*(4-2)=3.0
    # idx4 = 3.0 + 0.5*(5-3.0) = 4.0
    assert result.iloc[0] != result.iloc[0]  # NaN
    assert result.iloc[1] != result.iloc[1]  # NaN
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[3] == pytest.approx(3.0)
    assert result.iloc[4] == pytest.approx(4.0)


def test_ema_matches_reference_recursion() -> None:
    values = pd.Series(np.arange(1.0, 21.0))
    result = ema(values, 5)
    k = 2 / 6
    expected = np.full(20, np.nan)
    expected[4] = values.iloc[:5].mean()
    for i in range(5, 20):
        expected[i] = expected[i - 1] + k * (values.iloc[i] - expected[i - 1])
    assert np.allclose(result.iloc[4:].to_numpy(), expected[4:])


def test_ema_warmup_is_nan_not_zero() -> None:
    series = pd.Series([5.0, 6.0, 7.0])
    result = ema(series, 200)
    assert result.isna().all()


def test_ema_constant_series_converges_to_value() -> None:
    series = pd.Series([10.0] * 50)
    result = ema(series, 20)
    assert result.dropna().eq(10.0).all()


def test_ema_preserves_index() -> None:
    index = pd.date_range("2024-01-01", periods=30, freq="1h", tz="UTC")
    series = pd.Series(np.arange(30.0), index=index)
    result = ema(series, 10)
    assert result.index.equals(index)


def test_ema_rejects_bad_period() -> None:
    with pytest.raises(ValueError, match="positive"):
        ema(pd.Series([1.0, 2.0]), 0)


def test_ema_is_deterministic() -> None:
    series = pd.Series(np.linspace(1, 99, 120))
    first = ema(series, 30)
    second = ema(series, 30)
    assert first.equals(second)
