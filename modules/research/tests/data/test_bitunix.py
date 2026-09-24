"""Bitunix provider tests: spot-history/futures normalisation, pagination,
date boundaries and closed-candle integrity - no real network."""

from __future__ import annotations

import httpx
import pandas as pd
import pytest

from crypto_research.config import ExchangeSettings
from crypto_research.data.exchanges.base import ExchangeError
from crypto_research.data.exchanges.bitunix import (
    BitunixDataProvider,
    parse_futures_kline,
    parse_spot_kline,
)
from crypto_research.data.models import parse_end_bound_exclusive, parse_start_bound

FUT_PAGE = 200  # matches the real Bitunix futures kline page cap
SPOT_PAGE = 500  # matches the real Bitunix spot history page cap
BASE_MS = 1_789_905_600_000  # arbitrary 4h-aligned ms epoch
DAY0_MS = 86_400_000 * (BASE_MS // 86_400_000)  # 00:00 UTC of that day


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


def spot_row(ts_s: int, close: float) -> dict:
    ts = pd.Timestamp(ts_s, unit="s", tz="UTC")
    return {
        "symbol": "BTCUSDT",
        "open": f"{close - 10:.2f}",
        "high": f"{close + 5:.2f}",
        "low": f"{close - 15:.2f}",
        "close": f"{close:.2f}",
        "volume": "239.0952",
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def futures_page(oldest_ms: int, count: int, close_start: float = 80000.0) -> list[dict]:
    """Generate `count` rows, newest-first, newest = oldest_ms + count*4h."""
    return [
        futures_row(oldest_ms + (i + 1) * 4 * 3_600_000, close_start + i)
        for i in reversed(range(count))
    ]


def spot_page(oldest_s: int, count: int, close_start: float = 80000.0) -> list[dict]:
    """Generate `count` rows, newest-first, newest = oldest_s + count*4h."""
    return [
        spot_row(oldest_s + (i + 1) * 4 * 3600, close_start + i)
        for i in reversed(range(count))
    ]


def spot_rows(ms_times: list[int]) -> list[dict]:
    return [spot_row(t // 1000, 80000.0 + i) for i, t in enumerate(ms_times)]


SPOT_SNAPSHOT = [
    {"symbol": "BTCUSDT", "open": "80912", "high": "81491.74", "low": "80811.02",
     "close": "81079.92", "volume": "239.0952", "ts": "2026-09-20T16:00:00Z"},
    {"symbol": "BTCUSDT", "open": "80493.2", "high": "80969.31", "low": "80327.64",
     "close": "80912.01", "volume": "187.3792", "ts": "2026-09-20T12:00:00Z"},
]


class RecordingTransport(httpx.MockTransport):
    def __init__(self, pages: list[list[dict]]) -> None:
        super().__init__(handler=self._handle)
        self.pages = pages
        self.requests: list[dict] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(dict(request.url.params))
        index = len(self.requests) - 1
        payload = self.pages[index] if index < len(self.pages) else []
        code = "0" if "spot" in str(request.url) else 0
        return httpx.Response(200, json={"code": code, "msg": "Success", "data": payload})


def make_futures_provider(pages: list[list[dict]]) -> tuple[BitunixDataProvider, RecordingTransport]:
    transport = RecordingTransport(pages)
    provider = BitunixDataProvider(
        ExchangeSettings(page_delay_seconds=0), market="futures", http=httpx.Client(transport=transport)
    )
    return provider, transport


def make_spot_provider(pages: list[list[dict]]) -> tuple[BitunixDataProvider, RecordingTransport]:
    transport = RecordingTransport(pages)
    provider = BitunixDataProvider(
        ExchangeSettings(page_delay_seconds=0), market="spot", http=httpx.Client(transport=transport)
    )
    return provider, transport


# ------------------------------------------------------------------ #
# Normalisation
# ------------------------------------------------------------------ #

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
    candle = parse_spot_kline(spot_row(1789905600, 81079.92))
    assert candle.timestamp == pd.Timestamp(1789905600, unit="s", tz="UTC")
    assert candle.open == 81079.92 - 10
    assert candle.close == 81079.92
    assert candle.volume == 239.0952
    assert candle.quote_volume is None


# ------------------------------------------------------------------ #
# Futures pagination
# ------------------------------------------------------------------ #

def test_futures_pagination_chains_end_time_exclusive() -> None:
    page1 = futures_page(BASE_MS - FUT_PAGE * 4 * 3_600_000, FUT_PAGE)
    page2 = futures_page(BASE_MS - 2 * FUT_PAGE * 4 * 3_600_000, FUT_PAGE)
    provider, transport = make_futures_provider([page1, page2, []])

    df = provider.fetch_klines("BTCUSDT", "4h")

    assert len(transport.requests) == 3  # two pages + one empty (exhausted)
    assert "endTime" not in transport.requests[0]
    assert int(transport.requests[1]["endTime"]) == int(page1[-1]["time"])
    assert int(transport.requests[2]["endTime"]) == int(page2[-1]["time"])

    assert list(df.columns) == ["open", "high", "low", "close", "volume", "quote_volume"]
    assert df.index.is_monotonic_increasing
    assert str(df.index.tz) == "UTC"
    assert len(df) == 2 * FUT_PAGE
    assert df["close"].dtype == "float64"
    provider.close()


def test_futures_short_page_continues_until_empty() -> None:
    # short pages do NOT mean "exhausted" (exchange era-boundary behaviour):
    # paging continues until an empty page terminates the loop
    page1 = futures_page(BASE_MS - FUT_PAGE * 4 * 3_600_000, FUT_PAGE)
    page2 = futures_page(BASE_MS - FUT_PAGE * 4 * 3_600_000 - 2 * 4 * 3_600_000, 2)
    provider, transport = make_futures_provider([page1, page2, []])

    df = provider.fetch_klines("BTCUSDT", "4h")
    assert len(transport.requests) == 3
    assert len(df) == FUT_PAGE + 2
    provider.close()


def test_futures_deduplicates_overlapping_pages() -> None:
    page1 = futures_page(BASE_MS - FUT_PAGE * 4 * 3_600_000, FUT_PAGE)
    overlap = page1[-3:]  # oldest three rows repeated
    page2 = futures_page(BASE_MS - FUT_PAGE * 4 * 3_600_000 - 3 * 4 * 3_600_000, 3)
    provider, _ = make_futures_provider([page1, overlap + page2])

    df = provider.fetch_klines("BTCUSDT", "4h")
    assert len(df) == FUT_PAGE + 3  # duplicates dropped
    assert df.index.is_unique
    provider.close()


def test_futures_empty_history_raises_actionable_error() -> None:
    provider, _ = make_futures_provider([[]])
    with pytest.raises(ExchangeError, match="no candles"):
        provider.fetch_klines("BTCUSDT", "4h")
    provider.close()


def test_futures_empty_history_returns_empty_frame_when_allowed() -> None:
    provider, _ = make_futures_provider([[]])
    assert provider.fetch_klines("BTCUSDT", "4h", allow_empty=True).empty
    provider.close()


def test_futures_pagination_guard_aborts_non_progress() -> None:
    page = futures_page(BASE_MS - FUT_PAGE * 4 * 3_600_000, FUT_PAGE)
    provider, _ = make_futures_provider([page, page])
    with pytest.raises(ExchangeError, match="no progress"):
        provider.fetch_klines("BTCUSDT", "4h")
    provider.close()


# ------------------------------------------------------------------ #
# Spot history pagination (kline/history endpoint)
# ------------------------------------------------------------------ #

def test_spot_history_pages_backward_with_second_end_time() -> None:
    page1 = spot_page(BASE_MS // 1000 - SPOT_PAGE * 4 * 3600, SPOT_PAGE)
    page2 = spot_page(BASE_MS // 1000 - 2 * SPOT_PAGE * 4 * 3600, SPOT_PAGE)
    provider, transport = make_spot_provider([page1, page2, []])

    df = provider.fetch_klines("BTCUSDT", "4h")

    assert len(transport.requests) == 3
    # the history endpoint is used and endTime is in SECONDS
    assert int(transport.requests[0]["limit"]) == 500
    assert "endTime" not in transport.requests[0]
    # next page: endTime = oldest open of previous page - 1 second
    oldest_s = int(pd.Timestamp(page1[-1]["ts"]).timestamp())
    assert int(transport.requests[1]["endTime"]) == oldest_s - 1
    oldest2_s = int(pd.Timestamp(page2[-1]["ts"]).timestamp())
    assert int(transport.requests[2]["endTime"]) == oldest2_s - 1

    assert len(df) == 2 * SPOT_PAGE
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.is_monotonic_increasing
    assert df.index.is_unique
    provider.close()


def test_spot_history_page_size_capped() -> None:
    pages = [spot_page(BASE_MS // 1000 - SPOT_PAGE * 4 * 3600, 200)]
    provider, transport = make_spot_provider(pages + [[]])
    provider.fetch_klines("BTCUSDT", "4h")
    assert int(transport.requests[0]["limit"]) == 500
    provider.close()


# ------------------------------------------------------------------ #
# Date boundaries (1h / 4h / 1d)
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("tf,tf_ms", [("1h", 3_600_000), ("4h", 4 * 3_600_000), ("1d", 86_400_000)])
def test_date_only_start_begins_at_midnight_utc(tf: str, tf_ms: int) -> None:
    times = [DAY0_MS + i * tf_ms for i in range(24)]
    rows = [futures_row(t, 80000.0 + i) for i, t in enumerate(times)]
    provider, _ = make_futures_provider([rows])
    df = provider.fetch_klines("BTCUSDT", tf, start=str(pd.Timestamp(DAY0_MS, unit="ms", tz="UTC").date()))
    # first candle is exactly the requested day's 00:00 UTC open
    assert df.index.min() == pd.Timestamp(DAY0_MS, unit="ms", tz="UTC")
    provider.close()


@pytest.mark.parametrize("tf,tf_ms", [("1h", 3_600_000), ("4h", 4 * 3_600_000), ("1d", 86_400_000)])
def test_date_only_end_includes_whole_utc_day(tf: str, tf_ms: int) -> None:
    per_day = 86_400_000 // tf_ms
    times = [DAY0_MS + i * tf_ms for i in range(2 * per_day)]  # two full days
    rows = [futures_row(t, 80000.0 + i) for i, t in enumerate(times)]
    provider, _ = make_futures_provider([rows])
    df = provider.fetch_klines(
        "BTCUSDT",
        tf,
        start=str(pd.Timestamp(DAY0_MS, unit="ms", tz="UTC").date()),
        end=str(pd.Timestamp(DAY0_MS, unit="ms", tz="UTC").date()),
    )
    # --end <day> includes the whole UTC calendar day of that date
    assert df.index.min() == pd.Timestamp(DAY0_MS, unit="ms", tz="UTC")
    assert df.index.max() == pd.Timestamp(DAY0_MS + (per_day - 1) * tf_ms, unit="ms", tz="UTC")
    assert len(df) == per_day
    provider.close()


def test_timestamp_end_is_inclusive_instant() -> None:
    tf_ms = 4 * 3_600_000
    times = [DAY0_MS + i * tf_ms for i in range(6)]
    rows = [futures_row(t, 80000.0 + i) for i, t in enumerate(times)]
    provider, _ = make_futures_provider([rows])
    exact_end = pd.Timestamp(times[3], unit="ms", tz="UTC")
    df = provider.fetch_klines("BTCUSDT", "4h", end=str(exact_end))
    assert df.index.max() == pd.Timestamp(times[3], unit="ms", tz="UTC")
    provider.close()


def test_exact_pagination_boundary_no_overlap_no_gap() -> None:
    # page1 oldest == page2 newest (contiguous history) -> the union must be
    # gapless and duplicate-free across the page boundary
    tf_ms = 4 * 3_600_000
    newest1 = BASE_MS
    page1 = futures_page(newest1 - (FUT_PAGE - 1) * tf_ms, FUT_PAGE)
    page2_newest = newest1 - FUT_PAGE * tf_ms  # candle right after page1's oldest
    page2 = futures_page(page2_newest - (FUT_PAGE - 1) * tf_ms, FUT_PAGE)
    provider, _ = make_futures_provider([page1, page2])

    df = provider.fetch_klines("BTCUSDT", "4h")
    assert len(df) == 2 * FUT_PAGE
    assert df.index.is_unique
    # every consecutive pair advances by exactly one timeframe (no gaps)
    assert (df.index.to_series().diff().iloc[1:] == pd.Timedelta(milliseconds=tf_ms)).all()
    provider.close()


# ------------------------------------------------------------------ #
# Closed-candle integrity
# ------------------------------------------------------------------ #

def _rows_for(ms_times: list[int]) -> list[dict]:
    rows = [futures_row(t, 80000.0 + i) for i, t in enumerate(ms_times)]
    rows.reverse()  # API returns newest-first
    return rows


def test_in_progress_candle_excluded() -> None:
    now_ms = BASE_MS + 3 * 3_600_000  # 3h into the candle opening at BASE_MS
    rows = _rows_for([BASE_MS, BASE_MS - 4 * 3_600_000, BASE_MS - 8 * 3_600_000])
    provider, _ = make_futures_provider([rows])
    df = provider.fetch_klines("BTCUSDT", "4h", now=pd.Timestamp(now_ms, unit="ms", tz="UTC"))
    assert df.index.max() == pd.Timestamp(BASE_MS - 4 * 3_600_000, unit="ms", tz="UTC")
    provider.close()


def test_candle_closing_exactly_now_is_included() -> None:
    now_ms = BASE_MS + 4 * 3_600_000  # candle opening BASE_MS closes exactly now
    rows = _rows_for([BASE_MS, BASE_MS - 4 * 3_600_000])
    provider, _ = make_futures_provider([rows])
    df = provider.fetch_klines("BTCUSDT", "4h", now=pd.Timestamp(now_ms, unit="ms", tz="UTC"))
    assert df.index.max() == pd.Timestamp(BASE_MS, unit="ms", tz="UTC")
    provider.close()


def test_spot_snapshot_includes_in_progress_but_is_not_history() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/api/spot/v1/market/kline")
        return httpx.Response(200, json={"code": "0", "msg": "Success", "data": SPOT_SNAPSHOT})

    provider = BitunixDataProvider(
        ExchangeSettings(),
        market="spot",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    snapshot = provider.fetch_latest_snapshot("BTCUSDT", "4h")
    assert len(snapshot) == 2  # returned as-is (utility only)
    provider.close()


# ------------------------------------------------------------------ #
# Error plumbing
# ------------------------------------------------------------------ #

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


def test_invalid_timeframe_rejected() -> None:
    provider = BitunixDataProvider(ExchangeSettings(), market="futures")
    with pytest.raises(ValueError, match="timeframe"):
        provider.fetch_klines("BTCUSDT", "3m")


# ------------------------------------------------------------------ #
# Date boundary parsers
# ------------------------------------------------------------------ #

def test_date_boundary_parsers() -> None:
    assert parse_start_bound("2024-01-02") == pd.Timestamp("2024-01-02 00:00", tz="UTC")
    assert parse_start_bound("2024-01-02T13:30") == pd.Timestamp("2024-01-02 13:30", tz="UTC")
    assert parse_end_bound_exclusive("2024-01-02") == pd.Timestamp("2024-01-03 00:00", tz="UTC")
    assert parse_end_bound_exclusive("2024-01-02T13:30") == pd.Timestamp(
        "2024-01-02 13:30:00.001", tz="UTC"
    )
