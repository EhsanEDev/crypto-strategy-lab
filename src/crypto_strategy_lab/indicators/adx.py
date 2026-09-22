"""Average Directional Index (ADX) - Wilder method, TA-Lib-compatible.

This implementation mirrors ``ta_ADX.c`` from the TA-Lib project exactly
(verified against frozen TA-Lib reference vectors and, when available,
against the installed TA-Lib binary in the test suite). Declared
convention::

    Bar 0 is NOT used for DM/TR smoothing (no previous bar).

    +DM_t = high_t - high_{t-1}   if > (low_{t-1} - low_t) and > 0 else 0
    -DM_t = low_{t-1} - low_t     if > (high_t - high_{t-1}) and > 0 else 0
    TR_t  = max(high_t - low_t, |high_t - close_{t-1}|, |low_t - close_{t-1}|)

    Smoothed DM/TR: seeded with the *raw sum* of bars 1..period-1, then the
    Wilder recursion ``X = X - X/period + v/period`` from bar ``period``
    (this is ta_ADX.c's hybrid seeding: the initial window is a sum, not a
    mean). First valid at bar ``period``.

    +DI = 100 * smoothed(+DM) / smoothed(TR)   (first valid at bar ``period``)
    -DI = 100 * smoothed(-DM) / smoothed(TR)   (first valid at bar ``period``)
    DX  = 100 * |+DI - -DI| / (+DI + -DI)      (undefined when the DI sum is 0)

    ADX: seeded with the *mean* of the DX values of bars ``period..2*period-1``
    -> first valid ADX at bar ``2*period - 1`` (index 27 for period 14,
    exactly like TA-Lib's ADX lookback), then Wilder recursion
    ``ADX = ADX - (ADX - DX) / period``. Bars with undefined DX keep the
    previous ADX (carried forward, as ta_ADX.c does).

Bars before an output's first valid position are NaN (honest warm-up,
never filled).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .atr import true_range


def directional_movement(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Standard +DM / -DM series (bar 0 = 0, excluded from smoothing)."""
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


def ta_lib_wilder_smooth(values: pd.Series, period: int) -> pd.Series:
    """ta_ADX.c / ta_PLUS_DI.c smoothing for a series starting at original bar 1.

    Seed = raw sum of the first ``period - 1`` values, then the
    sum-preserving Wilder recursion ``X = X - X/period + v`` (the full
    value is added; the smoothing keeps a sum-like scale, which cancels
    out in the DI ratio). First valid at sub-position ``period - 1``,
    i.e. original bar ``period``.
    """
    arr = values.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan)
    if n < period:
        return pd.Series(out, index=values.index)
    inv = 1.0 / period
    state = arr[: period - 1].sum()
    for j in range(period - 1, n):
        state = state - state * inv + arr[j]
        out[j] = state
    return pd.Series(out, index=values.index)


def _adx_from_dx(dx_sub: pd.Series, period: int, target_index: pd.Index) -> pd.Series:
    """ADX over a DX sub-series (starting at original bar 1), ta_ADX.c style.

    Seed = mean of DX at original bars ``period..2*period-1`` (undefined DX
    values are skipped from the sum, matching the C code); first ADX at
    original bar ``2*period - 1``; later bars use the mean-preserving
    Wilder recursion ``ADX = ADX - (ADX - DX)/period`` and carry the
    previous ADX forward when DX is undefined.
    """
    arr = dx_sub.to_numpy(dtype=float)
    m = len(arr)
    out = np.full(m, np.nan)
    first_adx_pos = 2 * period - 2  # sub-position of original bar 2*period-1
    if m >= first_adx_pos + 1:
        seed_sum = np.nansum(arr[period - 1 : first_adx_pos + 1])
        prev_adx = seed_sum / period
        out[first_adx_pos] = prev_adx
        inv = 1.0 / period
        for j in range(first_adx_pos + 1, m):
            dx = arr[j]
            if not np.isnan(dx):
                prev_adx = prev_adx - (prev_adx - dx) * inv
            out[j] = prev_adx
    result = pd.Series(np.nan, index=target_index)
    result.loc[dx_sub.index] = out
    return result


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """ADX with +DI / -DI, original index preserved, NaN warm-up.

    First valid positions (TA-Lib convention): +DI/-DI at bar ``period``,
    ADX at bar ``2*period - 1``.
    """
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    if df.empty:
        return pd.DataFrame({"adx": [], "plus_di": [], "minus_di": []})

    # bars 1..n-1: bar 0 is excluded from smoothing (no previous bar)
    tr = true_range(df).iloc[1:]
    plus_dm, minus_dm = directional_movement(df)
    plus_dm, minus_dm = plus_dm.iloc[1:], minus_dm.iloc[1:]

    smooth_tr = ta_lib_wilder_smooth(tr, period)
    smooth_plus = ta_lib_wilder_smooth(plus_dm, period)
    smooth_minus = ta_lib_wilder_smooth(minus_dm, period)

    plus_di = 100.0 * smooth_plus / smooth_tr
    minus_di = 100.0 * smooth_minus / smooth_tr

    di_defined = smooth_tr.notna()
    di_sum = plus_di + minus_di
    dx_sub = pd.Series(np.nan, index=tr.index)
    valid_sum = di_defined & (di_sum != 0)
    dx_sub[valid_sum] = 100.0 * (plus_di[valid_sum] - minus_di[valid_sum]).abs() / di_sum[valid_sum]

    adx_values = _adx_from_dx(dx_sub, period, df.index)

    plus_di_full = pd.Series(np.nan, index=df.index)
    minus_di_full = pd.Series(np.nan, index=df.index)
    plus_di_full.loc[plus_di.index] = plus_di
    minus_di_full.loc[minus_di.index] = minus_di
    return pd.DataFrame({"adx": adx_values, "plus_di": plus_di_full, "minus_di": minus_di_full})
