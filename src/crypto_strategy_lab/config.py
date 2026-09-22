"""Central configuration for the research lab.

Configuration comes from two layers (later wins):

1. YAML file (``config/default.yaml`` by default) - defines assets,
   timeframes and all regime thresholds.
2. Environment variables / ``.env`` (via pydantic-settings) - runtime
   concerns such as API base URLs and data directories.

All thresholds are centralised here so they are never scattered in code
and can be swapped for experimentation without touching the code base.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default.yaml"

SCHEMA_VERSION = "1.0"

SUPPORTED_TIMEFRAMES = ("1h", "4h", "1d")


class ExchangeSettings(BaseModel):
    """Bitunix public API endpoints (no credentials needed)."""

    spot_base_url: str = "https://openapi.bitunix.com"
    futures_base_url: str = "https://fapi.bitunix.com"
    timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.5
    page_delay_seconds: float = 0.25
    # page sizes are capped server-side (verified live): futures 200, spot history 500
    futures_page_size: int = 200
    spot_history_page_size: int = 500
    # how many trailing stored candles a re-download refreshes (guards against
    # a previously stored not-yet-closed candle sticking around forever)
    refresh_tail_candles: int = 1
    # hard loop guard for pagination (pages per single fetch)
    max_pages: int = 5000

    @field_validator("futures_page_size", "spot_history_page_size", "refresh_tail_candles", "max_pages")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("must be >= 0")
        return v

    @field_validator("page_delay_seconds", "retry_backoff_seconds", "timeout_seconds")
    @classmethod
    def _non_negative_float(cls, v: float) -> float:
        if v < 0:
            raise ValueError("must be >= 0")
        return v


class RegimeConfig(BaseModel):
    """All thresholds for the v001 rule-based regime detector."""

    ema_fast: int = 50
    ema_slow: int = 200

    adx_period: int = 14
    adx_trend_threshold: float = 20.0

    atr_period: int = 14
    rsi_period: int = 14

    # HIGH_VOLATILITY when atr_pct exceeds this rolling percentile of its own
    # trailing history (computed strictly on past data - no lookahead).
    volatility_percentile: float = 90.0
    volatility_lookback: int = 200

    # fast EMA slope is measured over this many bars.
    slope_lookback: int = 5

    # Range requires volatility to be *below* this percentile of trailing
    # history, so an ADX-low bar inside a volatility spike is not RANGE.
    range_volatility_percentile: float = 80.0

    @field_validator(
        "ema_fast",
        "ema_slow",
        "adx_period",
        "atr_period",
        "rsi_period",
        "volatility_lookback",
        "slope_lookback",
    )
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be a positive integer")
        return v

    @field_validator("volatility_percentile", "range_volatility_percentile")
    @classmethod
    def _percentile(cls, v: float) -> float:
        if not 0.0 < v <= 100.0:
            raise ValueError("percentile must be within (0, 100]")
        return v

    @field_validator("adx_trend_threshold")
    @classmethod
    def _adx_threshold(cls, v: float) -> float:
        if not 0.0 < v < 100.0:
            raise ValueError("adx_trend_threshold must be within (0, 100)")
        return v

    @model_validator(mode="after")
    def _fast_below_slow(self) -> "RegimeConfig":
        if self.ema_fast >= self.ema_slow:
            raise ValueError(
                f"ema_fast ({self.ema_fast}) must be strictly smaller than ema_slow ({self.ema_slow})"
            )
        return self


class LabConfig(BaseModel):
    """Top-level lab configuration."""

    assets: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    timeframes: list[str] = Field(default_factory=lambda: ["1h", "4h", "1d"])
    regime_timeframe: str = "4h"
    default_market: str = "futures"  # "futures" (deep, paginated history) | "spot"
    exchange: ExchangeSettings = Field(default_factory=ExchangeSettings)
    regime: RegimeConfig = Field(default_factory=RegimeConfig)
    default_start: str = "2022-04-17"  # earliest futures history Bitunix serves

    # Populated from environment by ``load_config``; safe defaults for tests.
    data_dir: Path = PROJECT_ROOT / "data"
    reports_dir: Path = PROJECT_ROOT / "reports"
    log_level: str = "INFO"

    @field_validator("timeframes", "regime_timeframe", "default_market", mode="before")
    @classmethod
    def _normalize_timeframes(cls, value: Any) -> Any:
        if isinstance(value, list):
            out = []
            for tf in value:
                tf_norm = str(tf).lower()
                if tf_norm not in SUPPORTED_TIMEFRAMES:
                    raise ValueError(f"unsupported timeframe {tf!r}; allowed: {SUPPORTED_TIMEFRAMES}")
                out.append(tf_norm)
            return out
        if isinstance(value, str):
            if value in ("futures", "spot"):
                return value
            tf_norm = value.lower()
            if tf_norm not in SUPPORTED_TIMEFRAMES:
                raise ValueError(f"unsupported timeframe {value!r}; allowed: {SUPPORTED_TIMEFRAMES}")
            return tf_norm
        return value

    @model_validator(mode="after")
    def _regime_timeframe_configured(self) -> "LabConfig":
        if self.regime_timeframe not in self.timeframes:
            raise ValueError(
                f"regime_timeframe {self.regime_timeframe!r} must be one of the configured "
                f"timeframes {self.timeframes}"
            )
        if self.default_market not in ("futures", "spot"):
            raise ValueError(f"default_market must be 'futures' or 'spot', got {self.default_market!r}")
        return self

    def validate_symbols(self, symbols: list[str]) -> None:
        for symbol in symbols:
            normalized = symbol.upper()
            if not normalized.endswith("USDT") or not normalized.isalnum():
                raise ValueError(
                    f"unsupported symbol {symbol!r}: expected an alnum symbol ending in USDT (e.g. BTCUSDT)"
                )


class EnvSettings(BaseSettings):
    """Runtime settings resolved from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bitunix_spot_base_url: str | None = None
    bitunix_futures_base_url: str | None = None
    csl_data_dir: str = "data"
    csl_reports_dir: str = "reports"
    csl_log_level: str = "INFO"
    csl_config_path: str = "config/default.yaml"


def load_config(path: str | Path | None = None) -> LabConfig:
    """Load the YAML config and overlay environment overrides."""
    env = EnvSettings()
    cfg_path = Path(path or env.csl_config_path)
    if not cfg_path.is_absolute():
        cfg_path = PROJECT_ROOT / cfg_path

    raw: dict[str, Any] = {}
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"config file {cfg_path} must contain a YAML mapping")
        raw = loaded

    exchange_raw = raw.pop("exchange", {}) or {}
    if env.bitunix_spot_base_url:
        exchange_raw["spot_base_url"] = env.bitunix_spot_base_url
    if env.bitunix_futures_base_url:
        exchange_raw["futures_base_url"] = env.bitunix_futures_base_url
    raw["exchange"] = exchange_raw

    config = LabConfig(**raw)

    data_dir_path = Path(env.csl_data_dir)
    if not data_dir_path.is_absolute():
        data_dir_path = PROJECT_ROOT / data_dir_path
    config.data_dir = data_dir_path
    reports_dir_path = Path(env.csl_reports_dir)
    config.reports_dir = reports_dir_path if reports_dir_path.is_absolute() else PROJECT_ROOT / reports_dir_path
    config.log_level = os.getenv("CSL_LOG_LEVEL", env.csl_log_level).upper()
    return config


def data_dir(config: LabConfig) -> Path:
    return Path(config.data_dir)


def reports_dir(config: LabConfig) -> Path:
    return Path(config.reports_dir)
