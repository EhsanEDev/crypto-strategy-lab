"""Bitunix public market data provider.

Observed live API behaviour (documented on 2026-09, verified against the
real endpoints - no guessing)::

    Spot   GET https://openapi.bitunix.com/api/spot/v1/market/kline
           ?symbol=BTCUSDT&interval={60|240|D}
           -> {"code": "0", "msg": "Success", "data": [
                 {"symbol": "BTCUSDT", "open": "80912", "high": "...",
                  "low": "80811.02", "close": "81079.92",
                  "volume": "239.0952", "ts": "2026-09-20T16:00:00Z"}]}
           * rows are returned newest-first (descending)
           * at most 201 rows, `limit` is ignored, no pagination params
             -> spot history is effectively capped at ~201 candles

    Futures GET https://fapi.bitunix.com/api/v1/futures/market/kline
           ?symbol=BTCUSDT&interval={1h|4h|1d}&limit<=200&endTime=<ms epoch>
           -> {"code": 0, "data": [
                 {"open": "80448.4", "high": "80937.1", "low": "80287.7",
                  "close": "80871.5", "quoteVol": "206315575.99",
                  "baseVol": "2558.76", "time": "1789905600000"}],
              "msg": "Success"}
           * rows newest-first; `endTime` is *exclusive* by candle open time
             (returns candles opening strictly before endTime), so backward
             paging uses endTime = oldest open time of the previous page
           * limit is capped at 200 rows per page
           * history depth for 4h starts 2022-04-17 (BTC/ETH/SOL) - Bitunix
             does not serve 2020+ futures klines through this endpoint

Because the spot endpoint cannot serve research-scale history, the default
market is ``futures`` (also public, also key-less). Candle prices for the
same symbol reflect the same market prices; the chosen market is recorded
in dataset metadata. All normalisation is isolated in this module - the
rest of the lab never sees a Bitunix-specific field name.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import pandas as pd

from ..models import Candle, candles_to_dataframe, parse_timeframe, to_utc_timestamp
from .base import ExchangeError, normalize_symbol

logger = logging.getLogger(__name__)

FUTURES_MAX_PAGE = 200

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
    ) -> pd.DataFrame:
        symbol = normalize_symbol(symbol)
        tf = parse_timeframe(timeframe)
        start_ms = int(to_utc_timestamp(start).timestamp() * 1000) if start else None
        end_ms = int(to_utc_timestamp(end).timestamp() * 1000) if end else None

        if self.market == "spot":
            candles = self._fetch_spot(symbol, tf, start_ms)
        else:
            candles = self._fetch_futures(symbol, tf, start_ms, end_ms)

        if not candles:
            if allow_empty:
                return pd.DataFrame()
            raise ExchangeError(
                f"Bitunix returned no candles for {symbol} {tf.name} "
                f"(market={self.market}). Check the symbol listing and the requested date range; "
                f"note Bitunix futures history only starts around 2022-04-17."
            )
        df = candles_to_dataframe(candles)
        if start_ms is not None:
            df = df[df.index >= pd.Timestamp(start_ms, unit="ms", tz="UTC")]
        if end_ms is not None:
            df = df[df.index <= pd.Timestamp(end_ms + tf.seconds * 1000, unit="ms", tz="UTC")]
        if start_ms is not None and self.market == "spot" and not df.empty:
            requested_start = pd.Timestamp(start_ms, unit="ms", tz="UTC")
            if df.index.min() > requested_start:
                logger.warning(
                    "Bitunix spot kline serves only the latest ~201 candles (no pagination): "
                    "requested start %s but earliest available spot candle is %s.",
                    requested_start,
                    df.index.min(),
                )
        return df

    # ------------------------------------------------------------------ #
    # Spot (max ~201 candles, no pagination)
    # ------------------------------------------------------------------ #

    def _fetch_spot(self, symbol: str, tf: Any, start_ms: int | None) -> list[Candle]:
        interval = SPOT_INTERVAL_MAP[tf.name]
        data = self._request(
            f"{self.settings.spot_base_url}/api/spot/v1/market/kline",
            params={"symbol": symbol, "interval": interval},
        )
        candles = [parse_spot_kline(row) for row in data]
        candles.sort(key=lambda c: c.timestamp)
        if start_ms is not None:
            cutoff = pd.Timestamp(start_ms, unit="ms", tz="UTC")
            candles = [c for c in candles if c.timestamp >= cutoff]
            if candles and candles[0].timestamp > cutoff:
                logger.warning(
                    "Bitunix spot history is capped (~201 candles, no pagination): "
                    "start %s is older than the earliest spot candle %s.",
                    cutoff,
                    candles[0].timestamp,
                )
        return candles

    # ------------------------------------------------------------------ #
    # Futures (paginated, deep history)
    # ------------------------------------------------------------------ #

    def _fetch_futures(
        self, symbol: str, tf: Any, start_ms: int | None, end_ms: int | None
    ) -> list[Candle]:
        url = f"{self.settings.futures_base_url}/api/v1/futures/market/kline"
        # endTime is exclusive by open time; +1 timeframe keeps a candle that
        # opens exactly at the user's `end`.
        end_time_exclusive = end_ms + int(tf.seconds * 1000) if end_ms is not None else None

        collected: list[Candle] = []
        seen: set[int] = set()
        page = 0
        while True:
            params: dict[str, Any] = {
                "symbol": symbol,
                "interval": tf.name,
                "limit": FUTURES_MAX_PAGE,
            }
            if end_time_exclusive is not None:
                params["endTime"] = end_time_exclusive

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
            page += 1
            logger.debug("futures kline page %s: %s rows, oldest %s", page, len(data), oldest_ms)

            if len(data) < FUTURES_MAX_PAGE:
                break
            if start_ms is not None and oldest_ms <= start_ms:
                break
            if end_time_exclusive is not None and oldest_ms >= end_time_exclusive:
                break

            end_time_exclusive = oldest_ms
            if self.settings.page_delay_seconds > 0:
                time.sleep(self.settings.page_delay_seconds)

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
