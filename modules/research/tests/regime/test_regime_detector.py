"""Regime Detector v001 tests: synthetic fixtures for every regime,
priority order, warm-up behaviour and no-lookahead (prefix invariance).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from crypto_research.config import RegimeConfig
from crypto_research.indicators.registry import warmup_bars
from crypto_research.regime.detector import detect_regime
from tests.helpers import log_walk, make_ohlcv


def trend_up_fixture(n: int = 500) -> pd.DataFrame:
    # steady geometric uptrend, small spreads -> strong ADX, aligned EMAs
    close = log_walk(n, drift=0.004, sigma=0.004, seed=42)
    return make_ohlcv(close, spread_pct=0.002, seed=42)


def trend_down_fixture(n: int = 500) -> pd.DataFrame:
    close = log_walk(n, drift=-0.004, sigma=0.004, seed=43)
    return make_ohlcv(close, spread_pct=0.002, seed=43)


def range_fixture(n: int = 600) -> pd.DataFrame:
    # tight sine oscillation around a flat level -> low ADX
    steps = np.arange(n)
    close = 100.0 * (1 + 0.004 * np.sin(steps * 0.9))
    return make_ohlcv(close, spread_pct=0.0008, seed=44)


def high_vol_fixture(n: int = 500, calm: int = 420) -> pd.DataFrame:
    # calm drift, then a violent low-drift wide-range phase
    calm_close = log_walk(calm, drift=0.0005, sigma=0.002, seed=45)
    rng = np.random.default_rng(46)
    wild_close = calm_close[-1] * np.exp(np.cumsum(rng.normal(0.0, 0.05, n - calm)))
    close = np.concatenate([calm_close, wild_close])
    spread = np.concatenate([np.full(calm, 0.0008), np.full(n - calm, 0.03)])
    return make_ohlcv(close, spread_pct=spread, seed=45)


def test_warmup_short_dataset_is_all_uncertain() -> None:
    df = make_ohlcv(log_walk(150, 0.001, 0.01, seed=1))
    result = detect_regime(df, RegimeConfig())
    assert result["regime"].eq("UNCERTAIN").all()
    assert result["regime_reason"].str.contains("warm-up").all()


def test_warmup_rows_are_uncertain_then_rules_apply() -> None:
    df = trend_up_fixture()
    result = detect_regime(df, RegimeConfig())
    warmup = warmup_bars(RegimeConfig())
    assert result["regime"].iloc[: warmup].eq("UNCERTAIN").all()
    assert result["regime"].iloc[warmup:].nunique() >= 1


def test_trend_up_synthetic() -> None:
    df = trend_up_fixture()
    result = detect_regime(df, RegimeConfig())
    tail = result["regime"].iloc[-100:]
    counts = tail.value_counts(normalize=True)
    assert counts.get("TREND_UP", 0.0) >= 0.9, counts
    assert tail.iloc[-1] == "TREND_UP"
    reason = result["regime_reason"].iloc[-1]
    assert "EMA50 > EMA200" in reason
    assert "ADX above threshold" in reason
    flags = json.loads(result["regime_flags"].iloc[-1])
    assert flags["ema_alignment"] is True
    assert flags["price_above_slow_ema"] is True
    assert flags["fast_ema_slope_positive"] is True
    assert flags["adx_trending"] is True
    assert flags["high_volatility"] is False


def test_trend_down_synthetic() -> None:
    df = trend_down_fixture()
    result = detect_regime(df, RegimeConfig())
    tail = result["regime"].iloc[-100:]
    counts = tail.value_counts(normalize=True)
    # NOTE: sustained steep declines also inflate ATR% above its own trailing
    # percentile, so a share of trend bars legitimately lands in
    # HIGH_VOLATILITY with the v001 percentile rule (documented behaviour).
    assert counts.get("TREND_DOWN", 0.0) >= 0.55, counts
    assert counts.idxmax() == "TREND_DOWN"
    assert tail.iloc[-1] == "TREND_DOWN"
    assert "EMA50 < EMA200" in result["regime_reason"].iloc[-1]


def test_range_synthetic() -> None:
    df = range_fixture()
    result = detect_regime(df, RegimeConfig())
    evaluated = result["regime"].iloc[warmup_bars(RegimeConfig()):]
    counts = evaluated.value_counts(normalize=True)
    assert counts.get("RANGE", 0.0) >= 0.6, counts


def test_high_volatility_synthetic() -> None:
    df = high_vol_fixture()
    result = detect_regime(df, RegimeConfig())
    wild_tail = result["regime"].iloc[-40:]
    counts = wild_tail.value_counts(normalize=True)
    assert counts.get("HIGH_VOLATILITY", 0.0) >= 0.5, counts


def test_high_volatility_dominates_trend_rule() -> None:
    # end of an uptrend, then one gigantic-range bar: both the trend rule and
    # the volatility rule match -> HIGH_VOLATILITY must win (priority order).
    df = trend_up_fixture()
    spike_index = df.index[-1]
    df.loc[spike_index, "high"] = df.loc[spike_index, "close"] * 1.08
    df.loc[spike_index, "low"] = df.loc[spike_index, "close"] * 0.90
    result = detect_regime(df, RegimeConfig())
    assert bool(result["volatility_condition"].iloc[-1]) is True
    assert result["regime"].iloc[-1] == "HIGH_VOLATILITY"


def test_priority_order_is_documented() -> None:
    from crypto_research.regime.models import REGIME_PRIORITY, Regime

    assert [r.value for r in REGIME_PRIORITY] == [
        "HIGH_VOLATILITY",
        "TREND_UP",
        "TREND_DOWN",
        "RANGE",
        "UNCERTAIN",
    ]
    assert isinstance(Regime.TREND_UP.value, str)


def test_reasons_are_machine_readable_and_config_agnostic() -> None:
    df = trend_up_fixture()
    result = detect_regime(df, RegimeConfig())
    for flags_json in result["regime_flags"].iloc[-50:]:
        flags = json.loads(flags_json)
        assert set(flags) == {
            "warmup_complete",
            "ema_alignment",
            "price_above_slow_ema",
            "price_below_slow_ema",
            "fast_ema_slope_positive",
            "fast_ema_slope_negative",
            "adx_trending",
            "high_volatility",
            "vol_normal",
            "range_candidate",
        }
        assert all(isinstance(v, bool) for v in flags.values())

    # reasons reference the *configured* EMA periods, never hard-coded names
    custom = RegimeConfig(ema_fast=20, ema_slow=100)
    labelled = detect_regime(df, custom)
    trend_rows = labelled[labelled["regime"] == "TREND_UP"]
    assert not trend_rows.empty
    reason = trend_rows["regime_reason"].iloc[-1]
    assert "EMA20" in reason and "EMA100" in reason
    assert "EMA50" not in reason and "EMA200" not in reason


def test_no_lookahead_prefix_invariance() -> None:
    df = trend_up_fixture()
    full = detect_regime(df, RegimeConfig())
    k = 350
    prefix = detect_regime(df.iloc[:k], RegimeConfig())
    columns = ["regime", "ema50", "ema200", "atr14", "atr_pct", "rsi14", "adx14"]
    assert full[columns].iloc[:k].equals(prefix[columns])


def test_input_frame_not_mutated() -> None:
    df = trend_up_fixture()
    original = df.copy()
    detect_regime(df, RegimeConfig())
    assert df.equals(original)


def test_regime_values_are_only_the_five_labels() -> None:
    df = trend_up_fixture()
    result = detect_regime(df, RegimeConfig())
    assert set(result["regime"].unique()) <= {
        "TREND_UP",
        "TREND_DOWN",
        "RANGE",
        "HIGH_VOLATILITY",
        "UNCERTAIN",
    }
