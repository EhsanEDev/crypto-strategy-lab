"""Exponential Moving Average.

Deterministic, SMA-seeded, standard ``alpha = 2/(period+1)`` recursion.
Bars before the seed (index ``period - 1``) are NaN on purpose: EMA200 on a
fresh dataset is simply not defined for the first 199 candles and must not
be faked with fills.
"""

from __future__ import annotations

import pandas as pd

from ._smoothing import ema_smooth


def ema(series: pd.Series, period: int) -> pd.Series:
    """EMA of ``series`` with the original index preserved."""
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    if series.isna().any():
        raise ValueError("ema() requires a series without NaN values")
    return ema_smooth(series.astype(float), period)
