"""Massive (formerly Polygon.io) REST poller.

Uses the full-market snapshot endpoint filtered to the tracked tickers:

    GET https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT

Response (abridged): ``{"status": "OK", "count": 1, "tickers": [{"ticker": "AAPL",
"lastTrade": {"p": 190.1, "t": <ns>}, "min": {"c": ..., "t": <ms>}, "day": {"o", "c", ...},
"prevDay": {"c": ...}, "todaysChange": ..., "todaysChangePerc": ..., "updated": <ns>}]}``.
``lastTrade``/``lastQuote`` are only present when the plan includes trades/quotes.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)

MASSIVE_BASE_URL = "https://api.massive.com"
SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"
DEFAULT_POLL_INTERVAL = 15.0  # free tier: 5 calls/min
MAX_STARTUP_FAILURES = 3  # failed fetches before the first success that make Massive "unavailable"
STARTUP_RETRY_INTERVAL = 2.0  # retry quickly until the first success so a fallback isn't slow
ERROR_STATUSES = {"ERROR", "NOT_AUTHORIZED"}


@dataclass(frozen=True)
class SnapshotQuote:
    ticker: str
    price: float
    open_price: float | None  # previous close, so change % matches "today's change"
    timestamp: str | None


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _epoch_to_iso(value: Any) -> str | None:
    """Convert a Massive epoch timestamp (ns, us, ms or s, by magnitude) to ISO 8601 UTC."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if number > 10**17:
        seconds = number / 1e9
    elif number > 10**14:
        seconds = number / 1e6
    elif number > 10**11:
        seconds = number / 1e3
    else:
        seconds = float(number)
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat(timespec="milliseconds")


def parse_snapshot_item(item: dict) -> SnapshotQuote | None:
    """Pick the freshest available price from one snapshot entry, or None if unusable."""
    ticker = item.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        return None
    last_trade = item.get("lastTrade") or {}
    minute = item.get("min") or {}
    day = item.get("day") or {}
    prev_day = item.get("prevDay") or {}

    # Day bar is zeroed before the open, so fall through to the previous close.
    price = (
        _positive(last_trade.get("p"))
        or _positive(minute.get("c"))
        or _positive(day.get("c"))
        or _positive(prev_day.get("c"))
    )
    if price is None:
        return None
    open_price = _positive(prev_day.get("c")) or _positive(day.get("o"))
    timestamp = (
        _epoch_to_iso(last_trade.get("t"))
        or _epoch_to_iso(item.get("updated"))
        or _epoch_to_iso(minute.get("t"))
    )
    return SnapshotQuote(ticker.upper(), price, open_price, timestamp)


def parse_snapshot_response(payload: Any) -> list[SnapshotQuote]:
    """Parse a snapshot response body; malformed entries are skipped."""
    if not isinstance(payload, dict):
        return []
    items = payload.get("tickers")
    if not isinstance(items, list):
        return []
    quotes = []
    for item in items:
        if isinstance(item, dict) and (quote := parse_snapshot_item(item)):
            quotes.append(quote)
    return quotes


class MassiveDataSource(MarketDataSource):
    """Polls the Massive snapshot endpoint for all tracked tickers on an interval.

    Once a snapshot has succeeded, errors (network, auth, rate limits, bad
    payloads) are logged and the cache keeps its last prices; the next poll
    tries again. Before the first success, Massive is declared unavailable on
    a 401/403 or after ``max_startup_failures`` failed fetches: polling stops
    and ``on_unavailable(reason)`` is called once (see ``FallbackDataSource``).
    """

    def __init__(
        self,
        cache: PriceCache,
        api_key: str,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        base_url: str = MASSIVE_BASE_URL,
        client: httpx.AsyncClient | None = None,
        on_unavailable: Callable[[str], None] | None = None,
        max_startup_failures: int = MAX_STARTUP_FAILURES,
        startup_retry_interval: float = STARTUP_RETRY_INTERVAL,
    ) -> None:
        self.cache = cache
        self.api_key = api_key
        self.poll_interval = poll_interval
        self.base_url = base_url
        self.on_unavailable = on_unavailable
        self.max_startup_failures = max_startup_failures
        self.startup_retry_interval = startup_retry_interval
        self.has_succeeded = False
        self.unavailable_reason: str | None = None
        self._startup_failures = 0
        self._client = client
        self._owns_client = client is None
        self._tickers: list[str] = []
        self._task: asyncio.Task | None = None
        self._pending: set[asyncio.Task] = set()

    async def start(self, tickers: list[str]) -> None:
        for ticker in tickers:
            ticker = ticker.upper()
            if ticker not in self._tickers:
                self._tickers.append(ticker)
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10.0,
            )
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="massive-poller")
        logger.info(
            "Massive poller started: %d tickers every %.0fs", len(self._tickers), self.poll_interval
        )

    async def stop(self) -> None:
        tasks = [t for t in (self._task, *self._pending) if t is not None]
        self._task = None
        self._pending.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.upper()
        if ticker in self._tickers:
            return
        self._tickers.append(ticker)
        # Fetch it right away rather than waiting up to a full poll interval.
        if self._task is not None and self.unavailable_reason is None:
            task = asyncio.create_task(self.poll_once([ticker]))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper()
        if ticker in self._tickers:
            self._tickers.remove(ticker)
        self.cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    async def poll_once(self, tickers: list[str] | None = None) -> int:
        """Fetch one snapshot and write it to the cache. Returns the number of tickers updated."""
        requested = tickers if tickers is not None else list(self._tickers)
        if not requested or self._client is None or self.unavailable_reason is not None:
            return 0
        try:
            response = await self._client.get(
                SNAPSHOT_PATH, params={"tickers": ",".join(requested)}
            )
        except httpx.HTTPError as exc:
            self._failed(f"Massive request failed: {exc!r}")
            return 0

        status = response.status_code
        if status in (401, 403):
            if status == 401:
                hint = "the key is invalid"
            else:
                hint = "the snapshot endpoint needs a paid plan"
            self._failed(f"Massive API key rejected (HTTP {status}) — {hint}", fatal=True)
            return 0
        if status == 429:
            self._failed("Massive rate limit hit (HTTP 429); keeping last prices")
            return 0
        if status != 200:
            self._failed(f"Massive returned HTTP {status}: {response.text[:200]}")
            return 0
        try:
            payload = response.json()
        except ValueError:
            self._failed("Massive returned a non-JSON body")
            return 0
        if not isinstance(payload, dict):
            self._failed("Massive returned an unexpected body")
            return 0
        if payload.get("status") in ERROR_STATUSES:
            detail = payload.get("error") or payload.get("message") or payload["status"]
            self._failed(f"Massive returned an error response: {str(detail)[:200]}")
            return 0

        self.has_succeeded = True
        updated = 0
        for quote in parse_snapshot_response(payload):
            # Skip tickers removed while the request was in flight.
            if quote.ticker not in self._tickers:
                continue
            self.cache.update(quote.ticker, quote.price, quote.timestamp, open_price=quote.open_price)
            updated += 1
        return updated

    def _failed(self, message: str, fatal: bool = False) -> None:
        """Record a failed fetch; before the first success it may make Massive unavailable."""
        if not self.has_succeeded and self.unavailable_reason is None:
            self._startup_failures += 1
            if fatal:
                self._mark_unavailable(message)
                return
            if self._startup_failures >= self.max_startup_failures:
                self._mark_unavailable(
                    f"Massive returned no successful snapshot after {self._startup_failures} "
                    f"attempts (last error: {message})"
                )
                return
        logger.warning(message)

    def _mark_unavailable(self, reason: str) -> None:
        self.unavailable_reason = reason
        if self.on_unavailable is not None:
            self.on_unavailable(reason)
        else:
            logger.error("%s; Massive polling stopped", reason)

    async def _run(self) -> None:
        while self.unavailable_reason is None:
            try:
                await self.poll_once()
            except Exception:
                logger.exception("Massive poll failed")
            if self.unavailable_reason is not None:
                break
            if self.has_succeeded:
                await asyncio.sleep(self.poll_interval)
            else:
                await asyncio.sleep(min(self.poll_interval, self.startup_retry_interval))
