"""Configuration validation tests (cross-field robustness)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crypto_research.config import ExchangeSettings, LabConfig


def test_default_config_is_valid() -> None:
    config = LabConfig()
    assert config.regime_timeframe == "4h"
    assert config.regime_timeframe in config.timeframes
    assert config.regime.ema_fast < config.regime.ema_slow


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"ema_fast": 200, "ema_slow": 200}, "ema_fast"),
        ({"ema_fast": 200, "ema_slow": 50}, "ema_fast"),
        ({"volatility_percentile": 0}, "percentile"),
        ({"volatility_percentile": 101}, "percentile"),
        ({"range_volatility_percentile": 0}, "percentile"),
        ({"range_volatility_percentile": 100.1}, "percentile"),
        ({"adx_trend_threshold": 0}, "adx_trend_threshold"),
        ({"adx_trend_threshold": 100}, "adx_trend_threshold"),
        ({"ema_fast": 0}, "positive"),
        ({"volatility_lookback": -5}, "positive"),
    ],
)
def test_regime_config_rejects_bad_values(kwargs: dict, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        from crypto_research.config import RegimeConfig

        RegimeConfig(**kwargs)


def test_lab_config_rejects_regime_timeframe_not_in_timeframes() -> None:
    with pytest.raises(ValidationError, match="regime_timeframe"):
        LabConfig(timeframes=["1h", "1d"], regime_timeframe="4h")


def test_lab_config_rejects_unknown_timeframe() -> None:
    with pytest.raises(ValidationError, match="timeframe"):
        LabConfig(timeframes=["3m"])


def test_lab_config_rejects_bad_market() -> None:
    with pytest.raises(ValidationError, match="market"):
        LabConfig(default_market="margin")


def test_exchange_settings_reject_negative_values() -> None:
    with pytest.raises(ValidationError):
        ExchangeSettings(page_delay_seconds=-1)
    with pytest.raises(ValidationError):
        ExchangeSettings(max_pages=-1)


def test_symbols_validation() -> None:
    config = LabConfig()
    with pytest.raises(ValueError, match="USDT"):
        config.validate_symbols(["BTCUSD"])
