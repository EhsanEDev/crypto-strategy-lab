"""Average True Range (Wilder, TA-Lib-compatible).

True Range uses the standard definition::

    TR_t = max(high_t - low_t, |high_t - close_{t-1}|, |low_t - close_{t-1}|)

For the very first candle there is no previous close, so
``TR_0 = high_0 - low_0`` (the convention used by TA-Lib).

ATR smoothing method: **Wilder's smoothing** in the TA-Lib ``ta_ATR.c``
convention: the first ATR (at bar ``period``) is the simple mean of the
True Range of bars ``1..period`` (bar 0 is excluded - it has no previous
close), and later bars use the mean-preserving recursion
``ATR = (ATR*(period-1) + TR) / period``. The first valid ATR is at bar
``period`` (TA-Lib lookback), documented here so results are
reproducible; no external indicator library is used.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    """Standard True Range series (first bar = high - low)."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    tr = tr.astype(float)
    if len(df) > 0:
        tr.iloc[0] = float(df["high"].iloc[0] - df["low"].iloc[0])
    return tr


def atr(df: pd.DataFrame, period: int = 14, method: str = "wilder") -> pd.Series:
    """ATR with the original index preserved (first valid at bar ``period``)."""
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    if method != "wilder":
        raise ValueError(f"unsupported ATR method {method!r}; only 'wilder' is implemented")
    tr = true_range(df)
    arr = tr.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan)
    if n < period + 1:
        return pd.Series(out, index=tr.index)
    out[period] = arr[1 : period + 1].mean()
    for t in range(period + 1, n):
        out[t] = (out[t - 1] * (period - 1) + arr[t]) / period
    return pd.Series(out, index=tr.index)
