"""Canonical candle model shared by every exchange adapter.

All exchange-specific responses are normalised into this model before they
touch validation, storage or research code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
from pydantic import BaseModel, ConfigDict, field_validator

CANONICAL_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
OPTIONAL_COLUMNS = ["quote_volume", "trade_count"]
ALL_COLUMNS = CANONICAL_COLUMNS + OPTIONAL_COLUMNS


class Candle(BaseModel):
    """One canonical OHLCV candle (UTC)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float | None = None
    trade_count: int | None = None

    @field_validator("timestamp")
    @classmethod
    def _utc(cls, v: pd.Timestamp) -> pd.Timestamp:
        ts = pd.Timestamp(v)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert("UTC")

    @field_validator("open", "high", "low", "close")
    @classmethod
    def _positive_price(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("price must be strictly positive")
        return float(v)

    @field_validator("volume")
    @classmethod
    def _non_negative_volume(cls, v: float) -> float:
        if v < 0:
            raise ValueError("volume must be >= 0")
        return float(v)


@dataclass(frozen=True)
class Timeframe:
    """A canonical timeframe (e.g. ``4h``) plus its duration."""

    name: str
    duration: pd.Timedelta

    @property
    def seconds(self) -> float:
        return self.duration.total_seconds()


TIMEFRAME_MINUTES = {"1h": 60, "4h": 240}


def parse_timeframe(timeframe: str) -> Timeframe:
    """Parse canonical timeframes ``1h`` | ``4h`` | ``1d``."""
    tf = timeframe.strip().lower()
    if tf == "1h":
        return Timeframe("1h", pd.Timedelta(hours=1))
    if tf == "4h":
        return Timeframe("4h", pd.Timedelta(hours=4))
    if tf == "1d":
        return Timeframe("1d", pd.Timedelta(days=1))
    raise ValueError(f"unsupported timeframe {timeframe!r}; allowed: 1h, 4h, 1d")


def candles_to_dataframe(candles: list[Candle]) -> pd.DataFrame:
    """Build a canonical, timestamp-indexed OHLCV frame from candles."""
    if not candles:
        return _empty_ohlcv()
    frame = pd.DataFrame([c.model_dump() for c in candles])
    frame = frame.set_index("timestamp").sort_index()
    frame = frame.astype({c: "float64" for c in ["open", "high", "low", "close", "volume"]})
    # drop optional columns that carry no information for this exchange
    for optional in ("quote_volume", "trade_count"):
        if optional in frame.columns and frame[optional].isna().all():
            frame = frame.drop(columns=optional)
    return frame


def _empty_ohlcv() -> pd.DataFrame:
    index = pd.DatetimeIndex([], name="timestamp", tz="UTC")
    return pd.DataFrame({"open": [], "high": [], "low": [], "close": [], "volume": []}, index=index)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    """Parse a date/datetime string into a tz-aware UTC timestamp."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC")
