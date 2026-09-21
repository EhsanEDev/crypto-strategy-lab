"""Relative Strength Index - standard Wilder definition.

Wilder RSI (no external library)::

    delta_t      = close_t - close_{t-1}
    gain_t       = max(delta_t, 0),  loss_t = max(-delta_t, 0)
    avg_gain/loss: Wilder smoothing (SMA seed of the first ``period``
    deltas, then ``prev*(period-1) + current`` / ``period`` recursion)
    RS  = avg_gain / avg_loss
    RSI = 100 - 100 / (1 + RS)

Bars before ``period`` are NaN (warm-up). A perfectly rising series yields
RSI = 100, a falling one 0. When avg_loss is zero and avg_gain is positive
the RSI is defined as 100; both-zero windows stay NaN (undefined RS).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ._smoothing import wilder_smooth


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI with the original index preserved."""
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    if series.isna().any():
        raise ValueError("rsi() requires a series without NaN values")
    close = series.astype(float)

    delta = close.diff().iloc[1:]  # first delta is undefined
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = wilder_smooth(gain, period)
    avg_loss = wilder_smooth(loss, period)

    rs = np.divide(
        avg_gain.to_numpy(dtype=float),
        avg_loss.to_numpy(dtype=float),
        out=np.full(len(delta), np.nan),
        where=avg_loss.to_numpy(dtype=float) != 0,
    )
    values = 100.0 - 100.0 / (1.0 + rs)
    values[(avg_loss.to_numpy(dtype=float) == 0) & (avg_gain.to_numpy(dtype=float) > 0)] = 100.0

    result = pd.Series(np.nan, index=close.index)
    result.iloc[1:] = values
    return result
