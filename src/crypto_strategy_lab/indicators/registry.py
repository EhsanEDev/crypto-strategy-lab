"""Indicator registry: turns a raw OHLCV frame into the indicator dataset.

v001 indicators (all implemented locally with pandas/numpy, deterministic,
no lookahead)::

    EMA 50, EMA 200, ATR 14, RSI 14, ADX 14 (+ atr_pct = ATR/Close)

Column names follow the configured periods (``ema50`` for EMA(50), ...).
The registry is the only place where indicator columns are named, so
downstream code (regime, reports) stays decoupled from the formulas.
"""

from __future__ import annotations

import pandas as pd

from ..config import RegimeConfig
from .adx import adx
from .atr import atr
from .ema import ema
from .rsi import rsi

INDICATOR_COLUMNS = "ema_fast ema_slow atr atr_pct rsi adx adx_plus_di adx_minus_di".split()


def compute_indicators(df: pd.DataFrame, config: RegimeConfig) -> pd.DataFrame:
    """Attach v001 indicators to an OHLCV frame; returns a new frame."""
    if df.empty:
        raise ValueError("compute_indicators requires a non-empty OHLCV frame")
    for column in ("open", "high", "low", "close"):
        if df[column].isna().any():
            raise ValueError(f"column {column!r} contains NaN values")

    out = df.copy()
    close = df["close"]

    ema_fast = ema(close, config.ema_fast)
    ema_slow = ema(close, config.ema_slow)
    atr_values = atr(df, config.atr_period, method="wilder")
    rsi_values = rsi(close, config.rsi_period)
    adx_frame = adx(df, config.adx_period)

    out[f"ema{config.ema_fast}"] = ema_fast
    out[f"ema{config.ema_slow}"] = ema_slow
    out[f"atr{config.atr_period}"] = atr_values
    out["atr_pct"] = atr_values / close * 100.0
    out[f"rsi{config.rsi_period}"] = rsi_values
    out[f"adx{config.adx_period}"] = adx_frame["adx"]
    out["adx_plus_di"] = adx_frame["plus_di"]
    out["adx_minus_di"] = adx_frame["minus_di"]
    return out


def warmup_bars(config: RegimeConfig) -> int:
    """Bars required before every v001 indicator is defined.

    ADX needs ``2*adx_period - 2`` bars and EMA slow needs ``ema_slow - 1``
    bars; the binding constraint wins. regime detection treats any bar
    before this point (or with NaN indicators) as UNCERTAIN.
    """
    return max(config.ema_slow - 1, 2 * config.adx_period - 2, config.rsi_period, config.atr_period)
