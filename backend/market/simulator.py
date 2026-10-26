"""GBM market simulator with sector-correlated moves and occasional price shocks.

Each tick, every ticker's log return is driven by a one-factor-per-sector model:

    z_i = a_m * M + a_s * S_sector(i) + sqrt(1 - a_m^2 - a_s^2) * e_i

with M, S_k, e_i independent standard normals. That gives every z_i unit
variance, a correlation of a_m^2 across sectors and a_m^2 + a_s^2 within a
sector (tech names move together). The price then follows exact GBM:

    S_{t+dt} = S_t * exp((mu - sigma^2 / 2) dt + sigma sqrt(dt) z_i)
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass

import numpy as np

from .cache import PriceCache, utc_now_iso
from .interface import MarketDataSource

logger = logging.getLogger(__name__)

TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600
DEFAULT_INTERVAL = 0.5  # seconds between ticks
# Simulated market time runs faster than wall time so moves are visible in a demo:
# a 30% vol stock moves ~0.05% per tick, ~4% over an hour.
TIME_ACCELERATION = 30.0
DEFAULT_DT = DEFAULT_INTERVAL / TRADING_SECONDS_PER_YEAR * TIME_ACCELERATION

DEFAULT_EVENT_PROBABILITY = 0.0005  # per ticker per tick: ~1 shock every 100s across 10 tickers
EVENT_MIN_MOVE = 0.02
EVENT_MAX_MOVE = 0.05
MIN_PRICE = 0.01

MARKET_LOADING = 0.5


@dataclass(frozen=True)
class TickerProfile:
    seed_price: float
    mu: float  # annualized drift
    sigma: float  # annualized volatility
    sector: str | None = None
    sector_loading: float = 0.0


TICKER_PROFILES: dict[str, TickerProfile] = {
    "AAPL": TickerProfile(190.0, 0.08, 0.25, "tech", 0.6),
    "GOOGL": TickerProfile(175.0, 0.08, 0.28, "tech", 0.6),
    "MSFT": TickerProfile(420.0, 0.08, 0.24, "tech", 0.6),
    "AMZN": TickerProfile(185.0, 0.09, 0.30, "tech", 0.6),
    "TSLA": TickerProfile(250.0, 0.05, 0.55, "tech", 0.4),
    "NVDA": TickerProfile(135.0, 0.12, 0.50, "tech", 0.6),
    "META": TickerProfile(560.0, 0.09, 0.35, "tech", 0.6),
    "JPM": TickerProfile(210.0, 0.06, 0.20, "finance", 0.6),
    "V": TickerProfile(280.0, 0.06, 0.18, "finance", 0.6),
    "NFLX": TickerProfile(650.0, 0.08, 0.38, "tech", 0.5),
}

UNKNOWN_SEED_RANGE = (20.0, 400.0)
UNKNOWN_MU = 0.05
UNKNOWN_SIGMA = 0.35


class GBMEngine:
    """Pure price-path generator; no asyncio, no cache. Deterministic given ``seed``."""

    def __init__(
        self,
        dt: float = DEFAULT_DT,
        event_probability: float = DEFAULT_EVENT_PROBABILITY,
        seed: int | None = None,
        market_loading: float = MARKET_LOADING,
    ) -> None:
        self.dt = dt
        self.event_probability = event_probability
        self.market_loading = market_loading
        self.rng = np.random.default_rng(seed)
        self._profiles: dict[str, TickerProfile] = {}
        self._prices: dict[str, float] = {}
        self.last_events: dict[str, float] = {}

    @property
    def tickers(self) -> list[str]:
        return list(self._prices)

    @property
    def prices(self) -> dict[str, float]:
        return dict(self._prices)

    def profile(self, ticker: str) -> TickerProfile:
        return self._profiles[ticker.upper()]

    def add(self, ticker: str, price: float | None = None) -> float:
        """Track ``ticker`` (idempotent) and return its current price."""
        ticker = ticker.upper()
        if ticker in self._prices:
            return self._prices[ticker]
        profile = TICKER_PROFILES.get(ticker) or self._random_profile()
        self._profiles[ticker] = profile
        self._prices[ticker] = float(price) if price else profile.seed_price
        return self._prices[ticker]

    def remove(self, ticker: str) -> None:
        ticker = ticker.upper()
        self._prices.pop(ticker, None)
        self._profiles.pop(ticker, None)

    def _random_profile(self) -> TickerProfile:
        low, high = UNKNOWN_SEED_RANGE
        seed_price = round(math.exp(self.rng.uniform(math.log(low), math.log(high))), 2)
        return TickerProfile(seed_price, UNKNOWN_MU, UNKNOWN_SIGMA)

    def correlated_shocks(self, tickers: list[str]) -> np.ndarray:
        """Unit-variance normal shocks with the sector factor correlation structure."""
        n = len(tickers)
        market = self.rng.standard_normal()
        sectors = {p.sector for t in tickers if (p := self._profiles[t]).sector}
        sector_draws = {s: self.rng.standard_normal() for s in sorted(sectors)}
        idio = self.rng.standard_normal(n)

        shocks = np.empty(n)
        a_m = self.market_loading
        for i, ticker in enumerate(tickers):
            profile = self._profiles[ticker]
            a_s = profile.sector_loading if profile.sector else 0.0
            sector_term = a_s * sector_draws[profile.sector] if profile.sector else 0.0
            shocks[i] = a_m * market + sector_term + math.sqrt(1.0 - a_m**2 - a_s**2) * idio[i]
        return shocks

    def step(self) -> dict[str, float]:
        """Advance every ticker by one ``dt`` and return the new prices."""
        tickers = list(self._prices)
        self.last_events = {}
        if not tickers:
            return {}

        z = self.correlated_shocks(tickers)
        mu = np.array([self._profiles[t].mu for t in tickers])
        sigma = np.array([self._profiles[t].sigma for t in tickers])
        log_returns = (mu - 0.5 * sigma**2) * self.dt + sigma * math.sqrt(self.dt) * z

        if self.event_probability > 0:
            hits = self.rng.random(len(tickers)) < self.event_probability
            for i in np.flatnonzero(hits):
                move = self.rng.uniform(EVENT_MIN_MOVE, EVENT_MAX_MOVE) * self.rng.choice((-1.0, 1.0))
                log_returns[i] += math.log1p(move)
                self.last_events[tickers[i]] = move

        for ticker, r in zip(tickers, log_returns):
            self._prices[ticker] = max(self._prices[ticker] * math.exp(r), MIN_PRICE)
        return dict(self._prices)


class SimulatorDataSource(MarketDataSource):
    """Runs a ``GBMEngine`` in a background task, writing each tick into the cache."""

    def __init__(
        self,
        cache: PriceCache,
        interval: float = DEFAULT_INTERVAL,
        engine: GBMEngine | None = None,
    ) -> None:
        self.cache = cache
        self.interval = interval
        self.engine = engine or GBMEngine()
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        for ticker in tickers:
            self._seed(ticker)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="market-simulator")
        logger.info("Market simulator started with %d tickers", len(self.engine.tickers))

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def add_ticker(self, ticker: str) -> None:
        self._seed(ticker)

    async def remove_ticker(self, ticker: str) -> None:
        self.engine.remove(ticker)
        self.cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return self.engine.tickers

    def _seed(self, ticker: str) -> None:
        ticker = ticker.upper()
        if ticker in self.engine.tickers:
            return
        self.cache.update(ticker, self.engine.add(ticker))

    def tick(self) -> None:
        """Advance one step and publish all prices with a shared timestamp."""
        prices = self.engine.step()
        timestamp = utc_now_iso()
        for ticker, price in prices.items():
            self.cache.update(ticker, price, timestamp)
        for ticker, move in self.engine.last_events.items():
            logger.debug("Simulated event: %s %+.1f%%", ticker, move * 100)

    async def _run(self) -> None:
        while True:
            try:
                self.tick()
            except Exception:
                logger.exception("Market simulator tick failed")
            await asyncio.sleep(self.interval)
