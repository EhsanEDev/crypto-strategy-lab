"""RSI tests: hand-computed Wilder values and structural properties."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.indicators.rsi import rsi


def test_rsi_period_3_hand_computed_wilder() -> None:
    series = pd.Series([10.0, 12.0, 11.0, 13.0, 12.0, 14.0])
    result = rsi(series, period=3)
    # deltas: +2, -1, +2, -1, +2
    # seed avg_gain = (2+0+2)/3 = 4/3, avg_loss = (0+1+0)/3 = 1/3  (index 3)
    #   -> RS = 4 -> RSI = 80
    # index 4: gain (4/3*2+0)/3 = 8/9, loss (1/3*2+1)/3 = 5/9
    #   -> RS = 1.6 -> RSI = 61.538...
    # index 5: gain (8/9*2+2)/3 = 34/27, loss (5/9*2+0)/3 = 10/27
    #   -> RS = 3.4 -> RSI = 77.2727...
    assert result.iloc[:3].isna().all()
    assert result.iloc[3] == pytest.approx(80.0)
    assert result.iloc[4] == pytest.approx(100.0 - 100.0 / 2.6)
    assert result.iloc[5] == pytest.approx(77.27272727272727)


def test_rsi_warmup_is_nan() -> None:
    series = pd.Series(np.linspace(10, 20, 10))
    result = rsi(series, period=14)
    assert result.isna().all()


def test_rsi_strictly_rising_converges_to_100() -> None:
    series = pd.Series(np.arange(1.0, 61.0))
    result = rsi(series, period=14)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_rsi_strictly_falling_converges_to_0() -> None:
    series = pd.Series(np.arange(60.0, 0.0, -1.0))
    result = rsi(series, period=14)
    assert result.iloc[-1] == pytest.approx(0.0)


def test_rsi_bounds_and_reference_recursion() -> None:
    rng = np.random.default_rng(21)
    values = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 80))))
    result = rsi(values, period=7)
    valid = result.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()

    deltas = values.diff().iloc[1:]
    gains = deltas.clip(lower=0.0)
    losses = (-deltas).clip(lower=0.0)
    avg_gain = np.full(len(deltas), np.nan)
    avg_loss = np.full(len(deltas), np.nan)
    avg_gain[6] = gains.iloc[:7].mean()
    avg_loss[6] = losses.iloc[:7].mean()
    for i in range(7, len(deltas)):
        avg_gain[i] = (avg_gain[i - 1] * 6 + gains.iloc[i]) / 7
        avg_loss[i] = (avg_loss[i - 1] * 6 + losses.iloc[i]) / 7
    rs = avg_gain[6:] / avg_loss[6:]
    expected = 100.0 - 100.0 / (1.0 + rs)
    assert np.allclose(result.iloc[7:].to_numpy(), expected)


def test_rsi_requires_complete_series() -> None:
    with pytest.raises(ValueError, match="NaN"):
        rsi(pd.Series([1.0, np.nan, 3.0]), period=2)
