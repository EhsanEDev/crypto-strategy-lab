"""ATR tests against hand-computed expected values and TA-Lib ground truth."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.indicators.atr import atr, true_range

try:  # optional live cross-check against the official TA-Lib
    import talib as _talib
except Exception:  # pragma: no cover - talib is optional
    _talib = None


def _frame(
    high: list[float], low: list[float], close: list[float]
) -> pd.DataFrame:
    close_full = [close[0]] + close[:-1]  # prev close exists for every bar except first
    return pd.DataFrame(
        {
            "open": [10.0] * len(close_full),
            "high": high,
            "low": low,
            "close": close_full,
        }
    )


def test_true_range_standard_definition() -> None:
    df = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [102.0, 103.0, 104.0, 105.0],
            "low": [99.0, 100.0, 101.0, 102.0],
            "close": [101.0, 102.0, 103.0, 104.0],
        }
    )
    tr = true_range(df)
    # bar0: no prev close -> high - low = 3
    # bar1: max(103-100, |103-101|, |100-101|) = 3
    # bar2: max(104-101, |104-103|, |101-103|) = 3
    # bar3: max(105-102, |105-104|, |102-104|) = 3
    assert tr.tolist() == [3.0, 3.0, 3.0, 3.0]


def test_true_range_gap_move() -> None:
    df = pd.DataFrame(
        {
            "open": [100.0, 110.0],
            "high": [102.0, 112.0],
            "low": [99.0, 109.0],
            "close": [101.0, 111.0],
        }
    )
    tr = true_range(df)
    # bar1 gap up: max(112-109=3, |112-101|=11, |109-101|=8) = 11
    assert tr.tolist() == [3.0, 11.0]


def test_atr_period_3_hand_computed() -> None:
    df = pd.DataFrame(
        {
            "open": [11.0] * 5,
            "high": [12.0, 13.0, 14.0, 13.0, 15.0],
            "low": [10.0, 11.0, 12.0, 11.0, 13.0],
            "close": [11.0, 12.0, 13.0, 12.0, 14.0],
        }
    )
    # TR = [2, 2, 2, 2, 3]
    result = atr(df, period=3, method="wilder")
    # TA-Lib convention: first ATR at bar `period` = mean(TR bars 1..period)
    # ATR[3] = mean(TR[1..3]) = 2.0
    # ATR[4] = (ATR[3]*2 + TR[4]) / 3 = (4 + 3) / 3 = 7/3
    assert result.iloc[0] != result.iloc[0]
    assert result.iloc[1] != result.iloc[1]
    assert result.iloc[2] != result.iloc[2]
    assert result.iloc[3] == pytest.approx(2.0)
    assert result.iloc[4] == pytest.approx(7.0 / 3.0)


def test_atr_wilder_recursion_reference() -> None:
    rng = np.random.default_rng(11)
    n = 60
    df = pd.DataFrame(
        {
            "open": rng.uniform(90, 110, n),
            "high": rng.uniform(110, 120, n),
            "low": rng.uniform(80, 90, n),
            "close": rng.uniform(90, 110, n),
        }
    )
    tr = true_range(df)
    result = atr(df, period=4, method="wilder")
    expected = np.full(n, np.nan)
    expected[4] = tr.iloc[1:5].mean()  # mean TR bars 1..period
    for i in range(5, n):
        expected[i] = (expected[i - 1] * 3 + tr.iloc[i]) / 4
    assert np.allclose(result.to_numpy(), expected, atol=1e-12, equal_nan=True)


@pytest.mark.skipif(_talib is None, reason="talib optional live cross-check")
def test_atr_matches_talib() -> None:
    rng = np.random.default_rng(12)
    n = 120
    base = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
    spread = np.abs(rng.normal(0.004, 0.002, n))
    high = base * (1 + spread)
    low = base * (1 - spread)
    close = base * (1 + rng.normal(0, 0.002, n))
    df = pd.DataFrame({"open": close, "high": high, "low": low, "close": close})
    for period in (14, 7, 3):
        mine = atr(df, period=period, method="wilder")
        expected = _talib.ATR(high, low, close, timeperiod=period)
        assert np.allclose(mine.to_numpy(), expected, atol=1e-9, equal_nan=True)


def test_atr_warmup_is_nan() -> None:
    df = pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0],
            "high": [11.0, 12.0, 13.0],
            "low": [9.0, 10.0, 11.0],
            "close": [10.5, 11.5, 12.5],
        }
    )
    result = atr(df, period=14)
    assert result.isna().all()  # fewer than period+1 bars

def test_atr_first_valid_at_period() -> None:
    n = 40
    df = pd.DataFrame(
        {
            "open": np.full(n, 10.0),
            "high": np.arange(10.0, 10.0 + n) + 1.0,
            "low": np.arange(10.0, 10.0 + n) - 1.0,
            "close": np.arange(10.0, 10.0 + n),
        }
    )
    result = atr(df, period=14)
    assert result.iloc[:14].isna().all()
    assert result.notna().iloc[14]


def test_atr_rejects_unknown_method() -> None:
    df = pd.DataFrame({"open": [10], "high": [11], "low": [9], "close": [10]})
    with pytest.raises(ValueError, match="wilder"):
        atr(df, period=14, method="sma")
