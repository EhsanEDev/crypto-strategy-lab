"""Shared deterministic smoothing helpers (no lookahead).

Two smoothings are used in Milestone 1:

* **EMA** (``alpha = 2 / (period + 1)``) for EMA50/EMA200.
* **Wilder smoothing** (``alpha = 1 / period``) for ATR, RSI and ADX.

Both are seeded the classic way: the smoothing starts with the simple
average of the first ``period`` values, then applies the recursion
``x_t = x_{t-1} + alpha * (v_t - x_{t-1})``. Values before the seed are NaN
(honest warm-up behaviour - they are never faked or filled).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def smooth_series(values: pd.Series, period: int, alpha: float) -> pd.Series:
    """SMA-seeded recursive smoothing; NaN for the first ``period - 1`` bars."""
    smoothed = _smooth_array(values.to_numpy(dtype=float), period, alpha)
    return pd.Series(smoothed, index=values.index)


def wilder_smooth(values: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (``alpha = 1/period``; used by ATR, RSI, ADX)."""
    return smooth_series(values, period, 1.0 / period)


def ema_smooth(values: pd.Series, period: int) -> pd.Series:
    """Standard EMA smoothing (``alpha = 2/(period+1)``)."""
    return smooth_series(values, period, 2.0 / (period + 1))


def _smooth_array(values: np.ndarray, period: int, alpha: float) -> np.ndarray:
    n = len(values)
    out = np.full(n, np.nan)
    if n < period:
        return out
    out[period - 1] = values[:period].mean()
    for i in range(period, n):
        out[i] = out[i - 1] + alpha * (values[i] - out[i - 1])
    return out
