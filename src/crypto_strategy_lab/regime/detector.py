"""Regime Detector v001 - deterministic, rule-based, explainable.

Runs on the configured timeframe (default ``4h``). For every candle the
label and the exact conditions that produced it are stored; no lookahead
is used anywhere (verified by the prefix-invariance test).

Rule priority (top to bottom, see models.REGIME_PRIORITY)::

    1. HIGH_VOLATILITY : atr_pct > rolling percentile of its own trailing
                         history (threshold uses bars t-1 .. t-lookback)
    2. TREND_UP        : EMA_fast > EMA_slow  AND close > EMA_slow
                         AND EMA_fast slope > 0 AND ADX >= threshold
    3. TREND_DOWN      : EMA_fast < EMA_slow  AND close < EMA_slow
                         AND EMA_fast slope < 0 AND ADX >= threshold
    4. RANGE           : ADX < threshold AND atr_pct <= range percentile
    5. UNCERTAIN       : warm-up (NaN indicators) or no rule matched

Warm-up honesty: bars whose indicators are still NaN are UNCERTAIN, never
back-filled or guessed.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..config import RegimeConfig
from ..indicators.registry import compute_indicators
from .models import REGIME_PRIORITY, Regime, RegimeConditions

logger = logging.getLogger(__name__)


def rolling_volatility_threshold(
    atr_pct: pd.Series, lookback: int, percentile: float
) -> pd.Series:
    """Rolling percentile of ``atr_pct`` computed on *past* bars only.

    At bar ``t`` the threshold is the ``percentile`` of ``atr_pct`` over
    bars ``t-lookback .. t-1`` (``shift(1)`` makes the window strictly
    trailing, so the current bar can never set its own threshold).
    """
    return atr_pct.shift(1).rolling(lookback, min_periods=lookback).quantile(percentile / 100.0)


def high_volatility_mask(
    atr_pct: pd.Series, lookback: int, percentile: float
) -> pd.Series:
    """True where atr_pct exceeds its trailing rolling percentile."""
    threshold = rolling_volatility_threshold(atr_pct, lookback, percentile)
    return (atr_pct > threshold).fillna(False)


def detect_regime(df: pd.DataFrame, config: RegimeConfig) -> pd.DataFrame:
    """Classify every candle and attach indicators, conditions and reasons.

    ``df`` must be the canonical OHLCV frame (timestamp index, UTC).
    Returns a new frame; the input is never mutated.
    """
    if df.empty:
        raise ValueError("detect_regime requires a non-empty OHLCV frame")

    ind = compute_indicators(df, config)
    ema_fast = ind[f"ema{config.ema_fast}"]
    ema_slow = ind[f"ema{config.ema_slow}"]
    atr_pct = ind["atr_pct"]
    adx_col = ind[f"adx{config.adx_period}"]
    close = df["close"]

    warmup_complete = (
        ema_fast.notna() & ema_slow.notna() & atr_pct.notna() & adx_col.notna()
    )

    high_vol = high_volatility_mask(atr_pct, config.volatility_lookback, config.volatility_percentile)
    vol_normal_mask = ~high_volatility_mask(
        atr_pct, config.volatility_lookback, config.range_volatility_percentile
    )

    slope = ema_fast.diff(config.slope_lookback)
    ema_aligned_up = ema_fast > ema_slow
    ema_aligned_down = ema_fast < ema_slow
    price_above = close > ema_slow
    price_below = close < ema_slow
    slope_up = slope > 0
    slope_down = slope < 0
    adx_trending = adx_col >= config.adx_trend_threshold
    adx_ranging = adx_col < config.adx_trend_threshold

    up_rule = ema_aligned_up & price_above & slope_up & adx_trending
    down_rule = ema_aligned_down & price_below & slope_down & adx_trending
    range_rule = adx_ranging & vol_normal_mask

    rules = {
        Regime.HIGH_VOLATILITY: high_vol,
        Regime.TREND_UP: up_rule,
        Regime.TREND_DOWN: down_rule,
        Regime.RANGE: range_rule,
    }

    regime = np.full(len(df), Regime.UNCERTAIN.value, dtype=object)
    regime_mask = np.zeros(len(df), dtype=bool)
    for label in REGIME_PRIORITY:
        if label not in rules:  # UNCERTAIN is the fallback, never a rule
            continue
        mask = rules[label].fillna(False).to_numpy() & warmup_complete.to_numpy() & ~regime_mask
        regime[mask] = label.value
        regime_mask |= mask

    reasons: list[str] = []
    flags: list[str] = []
    for i in range(len(df)):
        conditions = RegimeConditions(
            warmup_complete=bool(warmup_complete.iloc[i]),
            ema_alignment=bool(ema_aligned_up.iloc[i] or ema_aligned_down.iloc[i]),
            price_above_slow_ema=bool(price_above.iloc[i]) if warmup_complete.iloc[i] else False,
            price_below_slow_ema=bool(price_below.iloc[i]) if warmup_complete.iloc[i] else False,
            fast_ema_slope_positive=bool(slope_up.iloc[i]) if warmup_complete.iloc[i] else False,
            fast_ema_slope_negative=bool(slope_down.iloc[i]) if warmup_complete.iloc[i] else False,
            adx_trending=bool(adx_trending.iloc[i]) if warmup_complete.iloc[i] else False,
            high_volatility=bool(high_vol.iloc[i]) if warmup_complete.iloc[i] else False,
            vol_normal=bool(vol_normal_mask.iloc[i]) if warmup_complete.iloc[i] else False,
            range_candidate=bool(range_rule.iloc[i]) if warmup_complete.iloc[i] else False,
        )
        flags.append(conditions.to_json())
        reasons.append(_build_reason(regime[i], conditions, config))

    out = ind.copy()
    out["regime"] = regime
    out["trend_condition"] = adx_trending.fillna(False).to_numpy()
    out["volatility_condition"] = high_vol.fillna(False).to_numpy()
    out["range_condition"] = range_rule.fillna(False).to_numpy()
    out["regime_reason"] = reasons
    out["regime_flags"] = flags

    logger.info("Regime detection complete: %s candles labelled", len(out))
    return out


def _build_reason(label: str, conditions: RegimeConditions, config: RegimeConfig) -> str:
    fast, slow = f"EMA{config.ema_fast}", f"EMA{config.ema_slow}"
    if not conditions.warmup_complete:
        return "Indicator warm-up incomplete; regime not evaluated"
    if label == Regime.HIGH_VOLATILITY.value:
        return (
            f"ATR% above rolling {config.volatility_percentile:g}th percentile "
            f"(lookback={config.volatility_lookback})"
        )
    if label == Regime.TREND_UP.value:
        return (
            f"{fast} > {slow}; close > {slow}; {fast} slope positive; ADX above threshold"
        )
    if label == Regime.TREND_DOWN.value:
        return (
            f"{fast} < {slow}; close < {slow}; {fast} slope negative; ADX above threshold"
        )
    if label == Regime.RANGE.value:
        return (
            f"ADX below threshold ({config.adx_trend_threshold:g}); "
            f"ATR% below rolling {config.range_volatility_percentile:g}th percentile"
        )
    if not conditions.ema_alignment:
        return (
            f"No rule matched: {fast} and {slow} not aligned for a trend; "
            "ADX/range rules unmatched"
        )
    if conditions.adx_trending:
        return "No rule matched: ADX trending but price/EMA/slope conditions incomplete"
    return "No rule matched: ADX between configurations; conditions ambiguous"
