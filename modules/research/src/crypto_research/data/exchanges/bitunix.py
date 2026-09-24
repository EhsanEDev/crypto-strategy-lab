"""Bitunix public market data provider.

Observed live API behaviour (documented 2026-09, verified against the real
endpoints - no guessing)::

    Spot history  GET https://openapi.bitunix.com/api/spot/v1/market/kline/history
           ?symbol=BTCUSDT&interval={60|240|D}&limit<=500&endTime=<unix SECONDS>
           -> {"code": "0", "msg": "Success", "data": [
                 {"symbol": "BTCUSDT", "open": "80912", "high": "...",
                  "low": "80811.02", "close": "81079.92",
                  "volume": "239.0952", "ts": "2026-09-20T16:00:00Z"}]}
           * rows newest-first; `ts` is the candle OPEN time (ISO-8601 UTC)
           * only CLOSED candles are returned (the in-progress candle is
             excluded server-side)
           * `limit` is capped at 500; asking for more returns an empty
             data array (no error) - always request <= 500
           * `endTime` is in SECONDS; exact boundary semantics differ
             between the exchange's hot/cold storage eras, but
             `endTime = oldest open of previous page - 1s` reliably pages
             backward with strictly older pages (verified 2026 + 2022 eras)
           * history depth: 4h candles back to 2017-08-17 for BTCUSDT
             (much deeper than futures; note pre-listing-era data is
             whatever the exchange serves - its provenance is Bitunix's)

    Spot snapshot GET https://openapi.bitunix.com/api/spot/v1/market/kline
           * latest ~201 candles only, no pagination, includes the
             in-progress candle. Retained as `fetch_latest_snapshot()`
             for utility - it is NOT historical downloading.

    Futures kline GET https://fapi.bitunix.com/api/v1/futures/market/kline
           ?symbol=BTCUSDT&interval={1h|4h|1d}&limit<=200&endTime=<ms epoch>
           -> {"code": 0, "data": [
                 {"open": "80448.4", "high": "80937.1", "low": "80287.7",
                  "close": "80871.5", "quoteVol": "206315575.99",
                  "baseVol": "2558.76", "time": "1789905600000"}],
              "msg": "Success"}
           * rows newest-first; `time` is the candle OPEN time (ms epoch)
           * `endTime` is EXCLUSIVE by candle open time
             (returns candles opening strictly before endTime), so backward
             paging uses endTime = oldest open time of the previous page
           * limit capped at 200 rows per page
           * INCLUDES the in-progress candle - the provider filters it out
             client-side (closed-candle integrity)
           * history depth: 4h from 2022-04-17; 1h depth is shorter for
             some symbols (e.g. SOL from 2024-05-15)

Date boundary semantics (provider-level, unambiguous UTC):

* ``start``: inclusive. ``YYYY-MM-DD`` begins at that day's 00:00 UTC; a
  timestamp input is the exact instant. Candles opening at/after start.
* ``end``: converted to an EXCLUSIVE boundary. ``YYYY-MM-DD`` includes the
  whole UTC calendar day (next-day 00:00 UTC exclusive); a timestamp input
  is an inclusive instant (that instant + 1ms exclusive). Candles opening
  strictly before the boundary.

All normalisation is isolated in this module - the rest of the lab never
sees a Bitunix-specific field name.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import pandas as pd

from ..models import (
    Candle,
    candles_to_dataframe,
    filter_closed_candles,
    parse_end_bound_exclusive,
    parse_start_bound,
    parse_timeframe,
)
from .base import ExchangeError, normalize_symbol

logger = logging.getLogger(__name__)

# Canonical timeframe -> Bitunix spot interval code (minutes / "D").
SPOT_INTERVAL_MAP = {"1h": "60", "4h": "240", "1d": "D"}


def parse_spot_kline(raw: dict[str, Any]) -> Candle:
    """Normalise one spot kline record into the canonical Candle."""
    return Candle(
        timestamp=pd.Timestamp(raw["ts"]),
        open=float(raw["open"]),
        high=float(raw["high"]),
        low=float(raw["low"]),
        close=float(raw["close"]),
        volume=float(raw["volume"]),
    )


def parse_futures_kline(raw: dict[str, Any]) -> Candle:
    """Normalise one futures kline record into the canonical Candle."""
    time_ms = int(raw["time"])
    return Candle(
        timestamp=pd.Timestamp(time_ms, unit="ms", tz="UTC"),
        open=float(raw["open"]),
        high=float(raw["high"]),
        low=float(raw["low"]),
        close=float(raw["close"]),
        volume=float(raw["baseVol"]),
        quote_volume=float(raw["quoteVol"]),
    )


class BitunixDataProvider:
    """Public Bitunix market data provider (no API key required)."""

    name = "bitunix"

    def __init__(
        self,
        settings: Any | None = None,
        market: str = "futures",
        http: httpx.Client | None = None,
    ) -> None:
        from ...config import ExchangeSettings

        self.settings = settings or ExchangeSettings()
        market = market.lower()
        if market not in ("spot", "futures"):
            raise ValueError(f"market must be 'spot' or 'futures', got {market!r}")
        self.market = market
        self._http = http
        self._owns_http = http is None

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=self.settings.timeout_seconds)
        return self._http

    def close(self) -> None:
        if self._owns_http and self._http is not None:
            self._http.close()
            self._http = None

    def __enter__(self) -> "BitunixDataProvider":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def fetch_klines(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
        allow_empty: bool = False,
        now: str | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        """Fetch CLOSED historical candles as a canonical UTC OHLCV frame.

        ``start`` is inclusive (date-only -> 00:00 UTC); ``end`` is
        converted to an exclusive boundary (date-only -> whole UTC day).
        In-progress candles are excluded (open + timeframe > now), where
        ``now`` defaults to the current UTC time (captured once per fetch;
        injectable for deterministic tests).
        """
        symbol = normalize_symbol(symbol)
        tf = parse_timeframe(timeframe)
        start_ts = parse_start_bound(start) if start else None
        end_boundary = parse_end_bound_exclusive(end) if end else None
        now_ts = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")

        if self.market == "spot":
            candles = self._fetch_spot_history(symbol, tf, start_ts, end_boundary)
        else:
            candles = self._fetch_futures(symbol, tf, start_ts, end_boundary)

        if not candles:
            if allow_empty:
                return pd.DataFrame()
            raise ExchangeError(
                f"Bitunix returned no candles for {symbol} {tf.name} "
                f"(market={self.market}). Check the symbol listing and the requested date range; "
                f"note Bitunix futures history only starts around 2022-04-17."
            )
        df = candles_to_dataframe(candles)
        if start_ts is not None:
            df = df[df.index >= start_ts]
        if end_boundary is not None:
            df = df[df.index < end_boundary]
        df = filter_closed_candles(df, tf.name, now_ts)
        if df.empty and not allow_empty:
            raise ExchangeError(
                f"Bitunix returned no closed candles for {symbol} {tf.name} in the requested range."
            )
        return df

    def fetch_latest_snapshot(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """Latest ~201 spot candles (utility snapshot, NOT historical data).

        Uses the spot snapshot endpoint, which includes the in-progress
        candle and has no pagination - never use this for research history.
        """
        symbol = normalize_symbol(symbol)
        tf = parse_timeframe(timeframe)
        interval = SPOT_INTERVAL_MAP[tf.name]
        data = self._request(
            f"{self.settings.spot_base_url}/api/spot/v1/market/kline",
            params={"symbol": symbol, "interval": interval},
        )
        candles = [parse_spot_kline(row) for row in data]
        candles.sort(key=lambda c: c.timestamp)
        return candles_to_dataframe(candles)

    # ------------------------------------------------------------------ #
    # Spot history (paginated, deep history, closed candles server-side)
    # ------------------------------------------------------------------ #

    def _fetch_spot_history(
        self,
        symbol: str,
        tf: Any,
        start_ts: pd.Timestamp | None,
        end_boundary: pd.Timestamp | None,
    ) -> list[Candle]:
        url = f"{self.settings.spot_base_url}/api/spot/v1/market/kline/history"
        interval = SPOT_INTERVAL_MAP[tf.name]
        page_size = self.settings.spot_history_page_size
        # exclusive boundary -> inclusive endTime (seconds); -1s keeps the
        # server's inclusive upper bound aligned with our exclusive boundary
        end_time_s = int(end_boundary.timestamp()) - 1 if end_boundary is not None else None
        start_s = int(start_ts.timestamp()) if start_ts is not None else None

        collected: list[Candle] = []
        seen: set[int] = set()
        previous_oldest_s: int | None = None
        for page_no in range(1, self.settings.max_pages + 1):
            params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": page_size}
            if end_time_s is not None:
                params["endTime"] = end_time_s

            data = self._request(url, params=params)
            if not data:
                break

            page_candles = [parse_spot_kline(row) for row in data]
            for candle in page_candles:
                ts_s = int(candle.timestamp.timestamp())
                if ts_s not in seen:
                    seen.add(ts_s)
                    collected.append(candle)

            oldest_s = min(int(c.timestamp.timestamp()) for c in page_candles)
            logger.debug("spot history page %s: %s rows, oldest %s", page_no, len(data), oldest_s)

            # progress guard: a page that does not move backward would loop forever
            if previous_oldest_s is not None and oldest_s >= previous_oldest_s:
                raise ExchangeError(
                    f"Bitunix spot history pagination made no progress at {oldest_s} "
                    f"(page {page_no}) - aborting to avoid an infinite loop."
                )
            previous_oldest_s = oldest_s

            # NOTE: short pages are NOT treated as "exhausted" (the exchange
            # serves short pages at cold-storage era boundaries); paging
            # continues until an empty page, the start bound, or the
            # progress guard terminates the loop.
            if start_s is not None and oldest_s <= start_s:
                break
            if end_time_s is not None and oldest_s >= end_time_s:
                break

            end_time_s = oldest_s - 1
            if self.settings.page_delay_seconds > 0:
                time.sleep(self.settings.page_delay_seconds)
        else:
            raise ExchangeError(
                f"Bitunix spot history exceeded the page guard ({self.settings.max_pages} pages) "
                f"for {symbol} {tf.name} - narrow the date range."
            )

        collected.sort(key=lambda c: c.timestamp)
        return collected

    # ------------------------------------------------------------------ #
    # Futures (paginated; in-progress candle filtered client-side)
    # ------------------------------------------------------------------ #

    def _fetch_futures(
        self,
        symbol: str,
        tf: Any,
        start_ts: pd.Timestamp | None,
        end_boundary: pd.Timestamp | None,
    ) -> list[Candle]:
        url = f"{self.settings.futures_base_url}/api/v1/futures/market/kline"
        page_size = self.settings.futures_page_size
        # endTime is exclusive by open time - it maps 1:1 onto our exclusive boundary
        end_time_ms = int(end_boundary.timestamp() * 1000) if end_boundary is not None else None
        start_ms = int(start_ts.timestamp() * 1000) if start_ts is not None else None

        collected: list[Candle] = []
        seen: set[int] = set()
        previous_oldest_ms: int | None = None
        for page_no in range(1, self.settings.max_pages + 1):
            params: dict[str, Any] = {"symbol": symbol, "interval": tf.name, "limit": page_size}
            if end_time_ms is not None:
                params["endTime"] = end_time_ms

            data = self._request(url, params=params)
            if not data:
                break

            page_candles = [parse_futures_kline(row) for row in data]
            for candle in page_candles:
                ts_ms = int(candle.timestamp.value // 1_000_000)
                if ts_ms not in seen:
                    seen.add(ts_ms)
                    collected.append(candle)

            oldest_ms = min(int(c.timestamp.value // 1_000_000) for c in page_candles)
            logger.debug("futures kline page %s: %s rows, oldest %s", page_no, len(data), oldest_ms)

            if previous_oldest_ms is not None and oldest_ms >= previous_oldest_ms:
                raise ExchangeError(
                    f"Bitunix futures pagination made no progress at {oldest_ms} "
                    f"(page {page_no}) - aborting to avoid an infinite loop."
                )
            previous_oldest_ms = oldest_ms

            # short pages are not treated as "exhausted" either; an empty
            # page (next request) terminates the loop.
            if start_ms is not None and oldest_ms <= start_ms:
                break
            if end_time_ms is not None and oldest_ms >= end_time_ms:
                break

            end_time_ms = oldest_ms
            if self.settings.page_delay_seconds > 0:
                time.sleep(self.settings.page_delay_seconds)
        else:
            raise ExchangeError(
                f"Bitunix futures kline exceeded the page guard ({self.settings.max_pages} pages) "
                f"for {symbol} {tf.name} - narrow the date range."
            )

        collected.sort(key=lambda c: c.timestamp)
        return collected

    # ------------------------------------------------------------------ #
    # HTTP plumbing
    # ------------------------------------------------------------------ #

    def _request(self, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                response = self._client().get(url, params=params)
                response.raise_for_status()
                payload = response.json()
                return self._unwrap(payload, url)
            except ExchangeError:
                raise
            except (httpx.HTTPError, ValueError) as exc:  # network / parsing
                last_error = exc
                if attempt < self.settings.max_retries:
                    backoff = self.settings.retry_backoff_seconds * attempt
                    logger.warning(
                        "Bitunix request failed (%s) - retrying in %.1fs (attempt %s/%s)",
                        exc,
                        backoff,
                        attempt,
                        self.settings.max_retries,
                    )
                    time.sleep(backoff)
        raise ExchangeError(
            f"Bitunix request failed after {self.settings.max_retries} attempts: {last_error}. "
            "Check network connectivity or try again later."
        )

    def _unwrap(self, payload: Any, url: str) -> list[dict[str, Any]]:
        if not isinstance(payload, dict) or "code" not in payload or "data" not in payload:
            raise ExchangeError(f"unexpected Bitunix response shape from {url}: {payload!r}")
        code = payload["code"]
        ok = (str(code) == "0") if isinstance(code, str) else (code == 0)
        if not ok:
            raise ExchangeError(
                f"Bitunix API error {code!r}: {payload.get('msg')!r} (url={url})"
            )
        data = payload["data"]
        return data if isinstance(data, list) else []
