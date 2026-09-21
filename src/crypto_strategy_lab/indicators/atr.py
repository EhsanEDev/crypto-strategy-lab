"""Average True Range (Wilder).

True Range uses the standard definition::

    TR_t = max(high_t - low_t, |high_t - close_{t-1}|, |low_t - close_{t-1}|)

For the very first candle there is no previous close, so
``TR_0 = high_0 - low_0`` (the convention used by TA-Lib).

ATR smoothing method: **Wilder's smoothing** (``alpha = 1/period``, SMA
seed of the first ``period`` TR values, then the recursive
``(prev * (period-1) + TR) / period`` equivalent). This is documented here
so results are reproducible; no external indicator library is used.
"""

from __future__ import annotations

import pandas as pd

from ._smoothing import wilder_smooth


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
    """ATR with the original index preserved."""
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    if method != "wilder":
        raise ValueError(f"unsupported ATR method {method!r}; only 'wilder' is implemented")
    tr = true_range(df)
    return wilder_smooth(tr, period)
