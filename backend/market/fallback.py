"""Massive with an automatic switch to the simulator when Massive can't supply prices."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from .interface import MarketDataSource
from .massive import MassiveDataSource

logger = logging.getLogger(__name__)


class FallbackDataSource(MarketDataSource):
    """Delegates to ``primary`` (Massive) until it reports itself unavailable, then
    switches for the rest of the process to a source built by ``fallback_factory``.

    The switch carries over the tracked tickers and starts the fallback straight
    away, so the cache fills immediately. All ticker changes and the switch are
    serialized by a lock, so none are lost while switching.
    """

    def __init__(
        self,
        primary: MassiveDataSource,
        fallback_factory: Callable[[], MarketDataSource],
    ) -> None:
        self.primary = primary
        self.fallback: MarketDataSource | None = None
        self._fallback_factory = fallback_factory
        self._lock = asyncio.Lock()
        self._switch_task: asyncio.Task | None = None
        self._stopped = False
        primary.on_unavailable = self._on_primary_unavailable

    @property
    def active(self) -> MarketDataSource:
        return self.fallback or self.primary

    @property
    def using_fallback(self) -> bool:
        return self.fallback is not None

    async def start(self, tickers: list[str]) -> None:
        self._stopped = False
        async with self._lock:
            await self.active.start(tickers)

    async def stop(self) -> None:
        self._stopped = True
        task = self._switch_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        async with self._lock:
            await self.primary.stop()
            if self.fallback is not None:
                await self.fallback.stop()

    async def add_ticker(self, ticker: str) -> None:
        async with self._lock:
            await self.active.add_ticker(ticker)

    async def remove_ticker(self, ticker: str) -> None:
        async with self._lock:
            await self.active.remove_ticker(ticker)

    def get_tickers(self) -> list[str]:
        return self.active.get_tickers()

    async def wait_for_switch(self) -> None:
        """Wait for an in-progress switch to finish (mainly for tests)."""
        if self._switch_task is not None:
            await asyncio.shield(self._switch_task)

    def _on_primary_unavailable(self, reason: str) -> None:
        # Called synchronously from inside the primary's poll; switch in a separate
        # task so stopping the primary doesn't cancel the code that called us.
        if self._stopped or self._switch_task is not None:
            return
        logger.warning("%s; falling back to the built-in simulator", reason)
        self._switch_task = asyncio.create_task(self._switch(), name="market-fallback-switch")

    async def _switch(self) -> None:
        async with self._lock:
            if self._stopped or self.fallback is not None:
                return
            tickers = self.primary.get_tickers()
            await self.primary.stop()
            fallback = self._fallback_factory()
            try:
                await fallback.start(tickers)
            except Exception:
                logger.exception("Failed to start the fallback market data source")
                return
            self.fallback = fallback
        logger.info("Simulator now supplying prices for %d tickers", len(tickers))
