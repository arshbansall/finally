"""Shared fixtures: a temp SQLite database, a stub price cache and a fake market source."""

from dataclasses import dataclass

import pytest

import db

DEFAULT_PRICES = {
    "AAPL": 190.0,
    "GOOGL": 175.0,
    "MSFT": 420.0,
    "AMZN": 185.0,
    "TSLA": 250.0,
    "NVDA": 120.0,
    "META": 500.0,
    "JPM": 200.0,
    "V": 280.0,
    "NFLX": 650.0,
}
NEW_TICKER_PRICE = 50.0


@dataclass(frozen=True)
class StubUpdate:
    ticker: str
    price: float
    previous_price: float
    open_price: float
    timestamp: str
    direction: str
    change: float
    change_pct: float

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class StubPriceCache:
    """Deterministic stand-in for market.PriceCache; tests set prices explicitly."""

    def __init__(self, prices: dict[str, float] | None = None):
        self._prices: dict[str, StubUpdate] = {}
        self.version = 0
        for ticker, price in (prices or {}).items():
            self.update(ticker, price)

    def get(self, ticker):
        return self._prices.get(ticker.upper())

    def get_price(self, ticker):
        update = self.get(ticker)
        return update.price if update else None

    def get_all(self):
        return dict(self._prices)

    def update(self, ticker, price, timestamp=None):
        ticker = ticker.upper()
        existing = self._prices.get(ticker)
        previous = existing.price if existing else price
        open_price = existing.open_price if existing else price
        direction = "up" if price > previous else "down" if price < previous else "flat"
        update = StubUpdate(
            ticker=ticker,
            price=price,
            previous_price=previous,
            open_price=open_price,
            timestamp=timestamp or "2026-10-26T15:00:00+00:00",
            direction=direction,
            change=round(price - open_price, 2),
            change_pct=round((price - open_price) / open_price * 100, 2),
        )
        self._prices[ticker] = update
        self.version += 1
        return update

    def remove(self, ticker):
        self._prices.pop(ticker.upper(), None)

    # Test helper
    set = update


class FakeMarketSource:
    """Stand-in for MarketDataSource: tracks tickers and prices new ones immediately."""

    def __init__(self, cache: StubPriceCache):
        self.cache = cache
        self.tickers: set[str] = set()
        self.started = False
        self.stopped = False

    async def start(self, tickers):
        self.started = True
        for ticker in tickers:
            await self.add_ticker(ticker)

    async def stop(self):
        self.stopped = True

    async def add_ticker(self, ticker):
        self.tickers.add(ticker)
        if self.cache.get(ticker) is None:
            self.cache.update(ticker, DEFAULT_PRICES.get(ticker, NEW_TICKER_PRICE))

    async def remove_ticker(self, ticker):
        self.tickers.discard(ticker)
        self.cache.remove(ticker)

    def get_tickers(self):
        return sorted(self.tickers)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Fresh, seeded SQLite database for each test."""
    path = tmp_path / "finally.db"
    monkeypatch.setenv("FINALLY_DB_PATH", str(path))
    db.init_db(path)
    return path


@pytest.fixture
def price_cache():
    return StubPriceCache(DEFAULT_PRICES)


@pytest.fixture
def market_source(price_cache):
    source = FakeMarketSource(price_cache)
    source.tickers.update(DEFAULT_PRICES)
    return source


@pytest.fixture
def app(db_path, monkeypatch, tmp_path):
    """The FastAPI app wired to the temp db, stub cache and fake market source."""
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.setenv("FINALLY_STATIC_DIR", str(tmp_path / "no-static"))
    import app.main as main

    monkeypatch.setattr(main, "PriceCache", lambda: StubPriceCache(DEFAULT_PRICES))
    monkeypatch.setattr(main, "create_market_data_source", FakeMarketSource)
    return main.create_app()


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client
