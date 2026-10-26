"""Abstract interface shared by the simulator and the Massive REST poller."""

from __future__ import annotations

from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    """A background producer that keeps a ``PriceCache`` current for a set of tickers."""

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin background updates into the cache for ``tickers``."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop background updates. Safe to call more than once."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Start tracking ``ticker``; the cache should get a price promptly."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking ``ticker`` and drop it from the cache."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Tickers currently tracked."""
