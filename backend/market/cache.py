"""In-memory price cache shared by the market data source, SSE stream and services."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal

Direction = Literal["up", "down", "flat"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class PriceUpdate:
    ticker: str
    price: float
    previous_price: float
    open_price: float  # session-open reference price, for daily change %
    timestamp: str  # ISO 8601 UTC
    direction: Direction
    change: float  # price - open_price
    change_pct: float  # (price - open_price) / open_price * 100

    def to_dict(self) -> dict:
        return asdict(self)


class PriceCache:
    """Latest price per ticker, plus previous and session-open prices.

    Writes come from a single background task, reads from request handlers and
    SSE streams; a lock keeps every operation atomic regardless of thread.
    ``version`` increments on every change so readers can cheaply detect updates.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prices: dict[str, PriceUpdate] = {}
        self._version = 0

    @property
    def version(self) -> int:
        return self._version

    def get(self, ticker: str) -> PriceUpdate | None:
        with self._lock:
            return self._prices.get(ticker.upper())

    def get_price(self, ticker: str) -> float | None:
        update = self.get(ticker)
        return update.price if update else None

    def get_all(self) -> dict[str, PriceUpdate]:
        with self._lock:
            return dict(self._prices)

    def update(
        self,
        ticker: str,
        price: float,
        timestamp: str | None = None,
        open_price: float | None = None,
    ) -> PriceUpdate:
        """Record a new price.

        ``open_price`` overrides the session-open reference (e.g. Massive's
        previous close); otherwise the first price seen for the ticker is used.
        """
        ticker = ticker.upper()
        price = round(float(price), 2)
        if price <= 0:
            raise ValueError(f"price must be positive, got {price} for {ticker}")

        with self._lock:
            existing = self._prices.get(ticker)
            previous = existing.price if existing else price
            if open_price is not None and open_price > 0:
                session_open = round(float(open_price), 2)
            elif existing:
                session_open = existing.open_price
            else:
                session_open = price

            if price > previous:
                direction: Direction = "up"
            elif price < previous:
                direction = "down"
            else:
                direction = "flat"

            change = price - session_open
            update = PriceUpdate(
                ticker=ticker,
                price=price,
                previous_price=previous,
                open_price=session_open,
                timestamp=timestamp or utc_now_iso(),
                direction=direction,
                # "+ 0.0" normalizes -0.0 so the UI never shows "-0.00%".
                change=round(change, 2) + 0.0,
                change_pct=round(change / session_open * 100, 2) + 0.0,
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def remove(self, ticker: str) -> None:
        with self._lock:
            if self._prices.pop(ticker.upper(), None) is not None:
                self._version += 1

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker.upper() in self._prices

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)
