"""Bitunix provider tests: normalization and pagination - no real network."""

from __future__ import annotations

import httpx
import pandas as pd
import pytest

from crypto_strategy_lab.config import ExchangeSettings
from crypto_strategy_lab.data.exchanges.base import ExchangeError
from crypto_strategy_lab.data.exchanges.bitunix import (
    BitunixDataProvider,
    parse_futures_kline,
    parse_spot_kline,
)

PAGE_SIZE = 200  # matches the real Bitunix futures kline page cap
BASE_MS = 1_789_905_600_000  # arbitrary 4h-aligned ms epoch


def futures_row(time_ms: int, close: float) -> dict:
    return {
        "open": f"{close - 100:.1f}",
        "high": f"{close + 50:.1f}",
        "low": f"{close - 150:.1f}",
        "close": f"{close:.1f}",
        "quoteVol": "1000000.0",
        "baseVol": "12.5",
        "time": str(time_ms),
    }


def futures_page(oldest_ms: int, count: int, close_start: float = 80000.0) -> list[dict]:
    """Generate `count` rows, newest-first, ending at oldest_ms (exclusive)."""
    return [
        futures_row(oldest_ms + (i + 1) * 4 * 3_600_000, close_start + i)
        for i in reversed(range(count))
    ]


SPOT_PAGE = [
    {"symbol": "BTCUSDT", "open": "80912", "high": "81491.74", "low": "80811.02",
     "close": "81079.92", "volume": "239.0952", "ts": "2026-09-20T16:00:00Z"},
    {"symbol": "BTCUSDT", "open": "80493.2", "high": "80969.31", "low": "80327.64",
     "close": "80912.01", "volume": "187.3792", "ts": "2026-09-20T12:00:00Z"},
]


def test_parse_futures_kline_normalizes_to_canonical() -> None:
    candle = parse_futures_kline(futures_row(1789905600000, 80871.5))
    assert candle.timestamp == pd.Timestamp(1789905600000, unit="ms", tz="UTC")
    assert candle.open == 80871.5 - 100
    assert candle.high == 80871.5 + 50
    assert candle.low == 80871.5 - 150
    assert candle.close == 80871.5
    assert candle.volume == 12.5  # base volume
    assert candle.quote_volume == 1_000_000.0


def test_parse_spot_kline_normalizes_to_canonical() -> None:
    candle = parse_spot_kline(SPOT_PAGE[0])
    assert candle.timestamp == pd.Timestamp("2026-09-20T16:00:00Z")
    assert candle.open == 80912.0
    assert candle.close == 81079.92
    assert candle.volume == 239.0952
    assert candle.quote_volume is None


class RecordingTransport(httpx.MockTransport):
    def __init__(self, pages: list[list[dict]]) -> None:
        super().__init__(handler=self._handle)
        self.pages = pages
        self.requests: list[dict] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(dict(request.url.params))
        index = len(self.requests) - 1
        payload = self.pages[index] if index < len(self.pages) else []
        return httpx.Response(200, json={"code": 0, "msg": "Success", "data": payload})


def make_futures_provider(pages: list[list[dict]]) -> tuple[BitunixDataProvider, RecordingTransport]:
    transport = RecordingTransport(pages)
    provider = BitunixDataProvider(
        ExchangeSettings(page_delay_seconds=0), market="futures", http=httpx.Client(transport=transport)
    )
    return provider, transport


def test_futures_pagination_chains_end_time_exclusive() -> None:
    page1 = futures_page(BASE_MS - PAGE_SIZE * 4 * 3_600_000, PAGE_SIZE)
    page2 = futures_page(BASE_MS - 2 * PAGE_SIZE * 4 * 3_600_000, PAGE_SIZE)
    provider, transport = make_futures_provider([page1, page2, []])

    df = provider.fetch_klines("BTCUSDT", "4h")

    assert len(transport.requests) == 3  # two pages + one empty (exhausted)
    assert "endTime" not in transport.requests[0]
    assert int(transport.requests[1]["endTime"]) == int(page1[-1]["time"])
    assert int(transport.requests[2]["endTime"]) == int(page2[-1]["time"])

    # normalization: ascending UTC index, canonical columns, correct types
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "quote_volume"]
    assert df.index.is_monotonic_increasing
    assert str(df.index.tz) == "UTC"
    assert len(df) == 2 * PAGE_SIZE
    assert df["close"].dtype == "float64"
    provider.close()


def test_futures_stops_when_page_short() -> None:
    page1 = futures_page(BASE_MS - PAGE_SIZE * 4 * 3_600_000, PAGE_SIZE)
    page2 = futures_page(BASE_MS - PAGE_SIZE * 4 * 3_600_000 - 2 * 4 * 3_600_000, 2)
    provider, transport = make_futures_provider([page1, page2, page2])  # third never fetched

    df = provider.fetch_klines("BTCUSDT", "4h")
    assert len(transport.requests) == 2
    assert len(df) == PAGE_SIZE + 2
    provider.close()


def test_futures_stops_at_requested_start() -> None:
    start_ms = BASE_MS - 3 * 4 * 3_600_000
    rows = futures_page(BASE_MS - PAGE_SIZE * 4 * 3_600_000, PAGE_SIZE)  # newest row = BASE_MS
    provider, transport = make_futures_provider([rows])

    df = provider.fetch_klines("BTCUSDT", "4h", start=str(pd.Timestamp(start_ms, unit="ms", tz="UTC")))
    assert df.index.min() == pd.Timestamp(start_ms, unit="ms", tz="UTC")
    assert df.index.max() == pd.Timestamp(BASE_MS, unit="ms", tz="UTC")
    provider.close()


def test_futures_end_includes_candle_opening_at_end() -> None:
    end_ms = BASE_MS
    rows = futures_page(end_ms - 2 * 4 * 3_600_000, 2)
    provider, _ = make_futures_provider([rows])

    df = provider.fetch_klines("BTCUSDT", "4h", end=str(pd.Timestamp(end_ms, unit="ms", tz="UTC")))
    assert df.index.max() == pd.Timestamp(end_ms, unit="ms", tz="UTC")
    provider.close()


def test_futures_deduplicates_overlapping_pages() -> None:
    page1 = futures_page(BASE_MS - PAGE_SIZE * 4 * 3_600_000, PAGE_SIZE)
    overlap = page1[-3:]  # oldest three rows repeated
    page2 = futures_page(BASE_MS - PAGE_SIZE * 4 * 3_600_000 - 3 * 4 * 3_600_000, 3)
    provider, _ = make_futures_provider([page1, overlap + page2])

    df = provider.fetch_klines("BTCUSDT", "4h")
    assert len(df) == PAGE_SIZE + 3  # duplicates dropped
    assert df.index.is_unique
    provider.close()


def test_futures_empty_history_raises_actionable_error() -> None:
    provider, _ = make_futures_provider([[]])
    with pytest.raises(ExchangeError, match="no candles"):
        provider.fetch_klines("BTCUSDT", "4h")
    provider.close()


def test_api_error_code_raises_exchange_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "400", "msg": "invalid symbol", "data": None})

    provider = BitunixDataProvider(
        ExchangeSettings(max_retries=1),
        market="futures",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ExchangeError, match="invalid symbol"):
        provider.fetch_klines("NOPE", "4h")
    provider.close()


def test_spot_fetch_returns_latest_candles_sorted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["interval"] == "240"
        return httpx.Response(200, json={"code": "0", "msg": "Success", "data": SPOT_PAGE})

    provider = BitunixDataProvider(
        ExchangeSettings(),
        market="spot",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    df = provider.fetch_klines("BTCUSDT", "4h")
    assert df.index.is_monotonic_increasing
    assert df.index[0] == pd.Timestamp("2026-09-20T12:00:00Z")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    provider.close()


def test_invalid_timeframe_rejected() -> None:
    provider = BitunixDataProvider(ExchangeSettings(), market="futures")
    with pytest.raises(ValueError, match="timeframe"):
        provider.fetch_klines("BTCUSDT", "3m")
