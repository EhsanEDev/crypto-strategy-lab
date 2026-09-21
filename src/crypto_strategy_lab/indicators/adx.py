"""Average Directional Index (ADX) - standard Wilder method.

Definitions (period ``n``, no external library, TA-Lib-compatible seeding)::

    +DM_t = high_t - high_{t-1}   if > (low_{t-1} - low_t) and > 0 else 0
    -DM_t = low_{t-1} - low_t     if > (high_t - high_{t-1}) and > 0 else 0

    TR_t: standard True Range (bar 0 = high - low, see atr.py)

    smoothed: Wilder smoothing (SMA seed over the first ``period`` values)
    +DI = 100 * smoothed(+DM) / smoothed(TR)
    -DI = 100 * smoothed(-DM) / smoothed(TR)
    DX  = 100 * |+DI - -DI| / (+DI + -DI)
    ADX = Wilder smoothing of DX (SMA seed over the first ``period`` DX
          values, so the first ADX appears at bar ``2*period - 2``)

The first ``2*period - 2`` ADX values are NaN (warm-up). ADX is the trend
strength input for regime detection; +DI/-DI are returned for explainability.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ._smoothing import wilder_smooth
from .atr import true_range


def directional_movement(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Standard +DM / -DM series (bar 0 = 0, TA-Lib convention)."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(0.0, index=df.index, dtype=float)
    minus_dm = pd.Series(0.0, index=df.index, dtype=float)
    plus_cond = (up > down) & (up > 0)
    minus_cond = (down > up) & (down > 0)
    plus_dm[plus_cond] = up[plus_cond]
    minus_dm[minus_cond] = down[minus_cond]
    if not df.empty:
        plus_dm.iloc[0] = 0.0
        minus_dm.iloc[0] = 0.0
    return plus_dm, minus_dm


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """ADX with +DI / -DI, original index preserved, NaN warm-up."""
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    if df.empty:
        return pd.DataFrame({"adx": [], "plus_di": [], "minus_di": []})

    tr = true_range(df)
    plus_dm, minus_dm = directional_movement(df)

    smooth_tr = wilder_smooth(tr, period)
    smooth_plus = wilder_smooth(plus_dm, period)
    smooth_minus = wilder_smooth(minus_dm, period)

    plus_di = 100.0 * smooth_plus / smooth_tr
    minus_di = 100.0 * smooth_minus / smooth_tr

    di_defined = smooth_tr.notna()
    di_sum = plus_di + minus_di
    dx = pd.Series(np.nan, index=df.index)
    valid_sum = di_defined & (di_sum != 0)
    dx[valid_sum] = 100.0 * (plus_di[valid_sum] - minus_di[valid_sum]).abs() / di_sum[valid_sum]
    dx[di_defined & (di_sum == 0)] = 0.0

    # ADX smooths the DX values; DX is undefined before the first DI values,
    # so smoothing starts from the first defined DX (bar `period - 1`) and
    # the first ADX appears at bar `2*period - 2`.
    adx_values = pd.Series(np.nan, index=df.index)
    dx_defined = dx.dropna()
    if len(dx_defined) >= period:
        smoothed = wilder_smooth(dx_defined, period)
        adx_values.loc[smoothed.index] = smoothed
    return pd.DataFrame({"adx": adx_values, "plus_di": plus_di, "minus_di": minus_di})
