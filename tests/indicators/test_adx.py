"""ADX tests: hand-verified structure, warm-up and trend strength."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.indicators.adx import adx, directional_movement


def test_directional_movement_standard_rules() -> None:
    df = pd.DataFrame(
        {
            "high": [10.0, 12.0, 13.0, 12.0],
            "low": [9.0, 10.0, 11.0, 10.5],
        }
    )
    plus_dm, minus_dm = directional_movement(df)
    # bar1: +DM = 12-10=2 (> -DM=9-10=-1 and >0); -DM = 0
    # bar2: +DM = 1 ; -DM = 0
    # bar3: up = 0 -> +DM=0 ; down = 11-10.5=0.5 -> -DM=0.5
    assert plus_dm.tolist() == [0.0, 2.0, 1.0, 0.0]
    assert minus_dm.tolist() == [0.0, 0.0, 0.0, 0.5]


def test_adx_warmup_and_bounds_on_trend() -> None:
    period = 14
    n = 300
    high = np.arange(10.0, 10.0 + n)  # straight staircase up
    low = high - 1.0
    close = (high + low) / 2
    df = pd.DataFrame({"open": close, "high": high, "low": low, "close": close})

    result = adx(df, period=period)
    adx_col = result["adx"]
    assert adx_col.iloc[: 2 * period - 2].isna().all()
    assert adx_col.notna().iloc[2 * period - 2]
    valid = adx_col.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()
    # a perfectly one-sided trend converges to a high ADX
    assert valid.iloc[-1] == pytest.approx(100.0)
    assert (result["plus_di"].dropna() > result["minus_di"].dropna()).all()


def test_adx_low_in_tight_range() -> None:
    period = 14
    n = 400
    base = 100.0 + 0.5 * np.sin(np.arange(n) * 0.7)  # tight oscillation
    df = pd.DataFrame(
        {
            "open": base,
            "high": base + 0.05,
            "low": base - 0.05,
            "close": base,
        }
    )
    result = adx(df, period=period)
    valid = result["adx"].dropna()
    assert (valid < 20).all()
    assert result["plus_di"].dropna().min() > 0  # both sides active
    assert result["minus_di"].dropna().min() > 0


def test_adx_matches_reference_recursion() -> None:
    period = 4
    rng = np.random.default_rng(31)
    n = 80
    base = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    spread = np.abs(rng.normal(0, 0.005, n))
    df = pd.DataFrame(
        {
            "open": base,
            "high": base * (1 + spread),
            "low": base * (1 - spread),
            "close": base,
        }
    )
    result = adx(df, period=period)

    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_dm[0] = minus_dm[0] = 0.0

    def wilder(series: np.ndarray) -> np.ndarray:
        out = np.full(len(series), np.nan)
        out[period - 1] = series[:period].mean()
        for i in range(period, len(series)):
            out[i] = (out[i - 1] * (period - 1) + series[i]) / period
        return out

    s_tr = wilder(tr.to_numpy())
    s_plus = wilder(plus_dm)
    s_minus = wilder(minus_dm)
    plus_di = 100.0 * s_plus / s_tr
    minus_di = 100.0 * s_minus / s_tr
    with np.errstate(invalid="ignore"):
        dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    dx[np.isnan(plus_di)] = np.nan
    adx_input = dx[~np.isnan(dx)]  # first defined DX at bar `period - 1`
    adx_expected = np.full(n, np.nan)
    if len(adx_input) >= period:
        seeded = np.full(len(adx_input), np.nan)
        seeded[period - 1] = adx_input[:period].mean()
        for i in range(period, len(adx_input)):
            seeded[i] = (seeded[i - 1] * (period - 1) + adx_input[i]) / period
        defined_positions = np.where(~np.isnan(dx))[0]
        adx_expected[defined_positions] = seeded
    assert np.allclose(result["adx"].to_numpy(), adx_expected, atol=1e-12, equal_nan=True)
    assert np.allclose(result["plus_di"].to_numpy(), plus_di, equal_nan=True)
    assert np.allclose(result["minus_di"].to_numpy(), minus_di, equal_nan=True)
