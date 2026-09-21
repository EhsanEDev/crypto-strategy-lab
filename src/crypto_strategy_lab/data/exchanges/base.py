"""Exchange-agnostic data provider interface.

The research engine (indicators, regime, reports) only ever talks to this
interface, never to an exchange-specific HTTP API. Adding Binance/Bybit
later means adding another ``ExchangeDataProvider`` implementation here.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class ExchangeDataProvider(Protocol):
    """Public market data provider (no credentials, read-only)."""

    name: str

    def fetch_klines(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles and return the canonical frame.

        Returns a DataFrame indexed by UTC ``timestamp`` with columns
        ``open, high, low, close, volume`` (+ optional ``quote_volume``),
        sorted ascending.
        """
        ...


class ExchangeError(RuntimeError):
    """Raised for actionable exchange/API failures."""


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()
