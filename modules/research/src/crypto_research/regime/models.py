"""Regime labels and per-candle explanation structures.

The detector is a *rule-based hypothesis generator*, not an oracle: every
candle carries the conditions that produced its label so results stay
explainable and auditable.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum


class Regime(str, Enum):
    """v001 regime labels."""

    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    UNCERTAIN = "UNCERTAIN"


# Explicit, deterministic classification priority (evaluated top to bottom):
#
#   1. HIGH_VOLATILITY   - volatility anomaly dominates everything else
#   2. TREND_UP          - full up-trend rule must match completely
#   3. TREND_DOWN        - full down-trend rule must match completely
#   4. RANGE             - low ADX and normal volatility
#   5. UNCERTAIN         - anything the rules cannot classify
REGIME_PRIORITY = [
    Regime.HIGH_VOLATILITY,
    Regime.TREND_UP,
    Regime.TREND_DOWN,
    Regime.RANGE,
    Regime.UNCERTAIN,
]


@dataclass
class RegimeConditions:
    """Machine-readable per-candle conditions (stored as JSON).

    Field names are configuration-agnostic (no hard-coded "EMA50"/"EMA200"):
    ``fast``/``slow`` refer to the configured EMA periods.
    """

    warmup_complete: bool = False
    ema_alignment: bool = False
    price_above_slow_ema: bool = False
    price_below_slow_ema: bool = False
    fast_ema_slope_positive: bool = False
    fast_ema_slope_negative: bool = False
    adx_trending: bool = False
    high_volatility: bool = False
    vol_normal: bool = False
    range_candidate: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)


def regime_flags_json(conditions: RegimeConditions) -> str:
    return conditions.to_json()
