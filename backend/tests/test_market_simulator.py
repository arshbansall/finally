import asyncio
import math

import numpy as np
import pytest

from market import GBMEngine, PriceCache, SimulatorDataSource
from market.simulator import (
    DEFAULT_DT,
    EVENT_MAX_MOVE,
    EVENT_MIN_MOVE,
    TICKER_PROFILES,
    UNKNOWN_SEED_RANGE,
)

DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def make_engine(tickers=DEFAULT_TICKERS, **kwargs) -> GBMEngine:
    kwargs.setdefault("seed", 42)
    kwargs.setdefault("event_probability", 0.0)
    engine = GBMEngine(**kwargs)
    for ticker in tickers:
        engine.add(ticker)
    return engine


def log_returns(engine: GBMEngine, steps: int) -> np.ndarray:
    tickers = engine.tickers
    prices = np.empty((steps + 1, len(tickers)))
    prices[0] = [engine.prices[t] for t in tickers]
    for i in range(steps):
        new = engine.step()
        prices[i + 1] = [new[t] for t in tickers]
    return np.diff(np.log(prices), axis=0)


def test_default_tickers_have_realistic_seed_prices():
    engine = make_engine()
    assert set(DEFAULT_TICKERS) <= set(TICKER_PROFILES)
    assert engine.prices["AAPL"] == pytest.approx(190.0)
    assert engine.prices["GOOGL"] == pytest.approx(175.0)
    for price in engine.prices.values():
        assert 10 < price < 2000


def test_unknown_ticker_gets_plausible_seed_price():
    engine = make_engine([])
    price = engine.add("PYPL")
    low, high = UNKNOWN_SEED_RANGE
    assert low <= price <= high
    assert engine.add("pypl") == price  # idempotent, case-insensitive
    assert engine.tickers == ["PYPL"]


def test_remove_ticker():
    engine = make_engine(["AAPL", "MSFT"])
    engine.remove("aapl")
    assert engine.tickers == ["MSFT"]
    assert set(engine.step()) == {"MSFT"}


def test_step_with_no_tickers():
    assert make_engine([]).step() == {}


def test_seeded_engine_is_deterministic():
    a = make_engine(seed=7, event_probability=0.01)
    b = make_engine(seed=7, event_probability=0.01)
    for _ in range(50):
        assert a.step() == b.step()


def test_prices_stay_positive_and_sane_over_long_run():
    engine = make_engine(event_probability=0.002)
    start = engine.prices
    for _ in range(20_000):  # ~2.8 hours of ticks
        prices = engine.step()
    for ticker, price in prices.items():
        assert price > 0
        assert 0.2 < price / start[ticker] < 5


def test_prices_stay_positive_under_extreme_volatility():
    engine = make_engine(["TSLA"], dt=1.0)  # one full year per step
    for _ in range(2_000):
        assert engine.step()["TSLA"] >= 0.01


def test_log_returns_match_gbm_moments():
    engine = make_engine(["AAPL", "TSLA"], seed=1)
    returns = log_returns(engine, 40_000)
    for j, ticker in enumerate(engine.tickers):
        profile = TICKER_PROFILES[ticker]
        expected_sd = profile.sigma * math.sqrt(DEFAULT_DT)
        expected_mean = (profile.mu - 0.5 * profile.sigma**2) * DEFAULT_DT
        sd = returns[:, j].std()
        assert sd == pytest.approx(expected_sd, rel=0.03)
        # Mean is tiny relative to sd; check it's within ~4 standard errors.
        assert abs(returns[:, j].mean() - expected_mean) < 4 * expected_sd / math.sqrt(len(returns))


def test_log_returns_are_roughly_normal_without_events():
    engine = make_engine(["MSFT"], seed=3)
    r = log_returns(engine, 40_000)[:, 0]
    z = (r - r.mean()) / r.std()
    assert abs(np.mean(z**3)) < 0.1  # skew ~ 0
    assert abs(np.mean(z**4) - 3) < 0.2  # kurtosis ~ 3


def test_correlated_shocks_have_unit_variance():
    engine = make_engine()
    shocks = np.array([engine.correlated_shocks(engine.tickers) for _ in range(20_000)])
    np.testing.assert_allclose(shocks.std(axis=0), 1.0, atol=0.03)


def test_sector_correlation_is_present():
    engine = make_engine(DEFAULT_TICKERS + ["PYPL"], seed=11)
    returns = log_returns(engine, 20_000)
    corr = np.corrcoef(returns, rowvar=False)
    idx = {t: i for i, t in enumerate(engine.tickers)}

    def c(a, b):
        return corr[idx[a], idx[b]]

    # Same sector: market 0.5^2 + sector 0.6^2 = 0.61
    assert c("AAPL", "MSFT") == pytest.approx(0.61, abs=0.05)
    assert c("JPM", "V") == pytest.approx(0.61, abs=0.05)
    # Cross sector / unknown ticker: market factor only = 0.25
    assert c("AAPL", "JPM") == pytest.approx(0.25, abs=0.05)
    assert c("AAPL", "PYPL") == pytest.approx(0.25, abs=0.05)
    assert c("AAPL", "MSFT") > c("AAPL", "JPM") + 0.2


def test_events_produce_2_to_5_percent_jumps():
    engine = make_engine(["AAPL", "JPM"], seed=5, event_probability=0.05)
    seen = {}
    for _ in range(2_000):
        before = engine.prices
        after = engine.step()
        for ticker, move in engine.last_events.items():
            seen[ticker] = move
            assert EVENT_MIN_MOVE <= abs(move) <= EVENT_MAX_MOVE
            # Jump dominates the regular diffusion move for that tick.
            actual = after[ticker] / before[ticker] - 1
            assert actual == pytest.approx(move, abs=0.006)
    assert set(seen) == {"AAPL", "JPM"}


def test_events_go_both_ways_and_respect_probability():
    engine = make_engine(DEFAULT_TICKERS, seed=9, event_probability=0.01)
    moves = []
    steps = 5_000
    for _ in range(steps):
        engine.step()
        moves.extend(engine.last_events.values())
    expected = steps * len(DEFAULT_TICKERS) * 0.01
    assert abs(len(moves) - expected) < 4 * math.sqrt(expected)
    assert any(m > 0 for m in moves) and any(m < 0 for m in moves)


def test_no_events_when_probability_zero():
    engine = make_engine()
    for _ in range(1_000):
        engine.step()
        assert engine.last_events == {}


# --- SimulatorDataSource ---------------------------------------------------


async def test_start_seeds_cache_immediately():
    cache = PriceCache()
    source = SimulatorDataSource(cache, engine=make_engine([]))
    await source.start(["AAPL", "googl"])
    try:
        assert cache.get_price("AAPL") == 190.0
        assert cache.get_price("GOOGL") == 175.0
        assert sorted(source.get_tickers()) == ["AAPL", "GOOGL"]
    finally:
        await source.stop()


async def test_add_ticker_appears_in_cache_immediately():
    cache = PriceCache()
    source = SimulatorDataSource(cache, engine=make_engine([]))
    await source.add_ticker("pypl")
    update = cache.get("PYPL")
    assert update is not None and update.price > 0
    assert source.get_tickers() == ["PYPL"]
    await source.add_ticker("PYPL")  # idempotent: does not reset the price
    assert cache.get("PYPL") == update


async def test_remove_ticker_drops_from_cache_and_engine():
    cache = PriceCache()
    source = SimulatorDataSource(cache, engine=make_engine([]))
    await source.add_ticker("AAPL")
    await source.remove_ticker("aapl")
    assert cache.get("AAPL") is None
    assert source.get_tickers() == []
    source.tick()
    assert cache.get("AAPL") is None


async def test_tick_writes_all_prices_with_shared_timestamp():
    cache = PriceCache()
    source = SimulatorDataSource(cache, engine=make_engine([]))
    await source.add_ticker("AAPL")
    await source.add_ticker("MSFT")
    version = cache.version
    source.tick()
    assert cache.version == version + 2
    a, m = cache.get("AAPL"), cache.get("MSFT")
    assert a.timestamp == m.timestamp
    assert a.previous_price == 190.0 and a.open_price == 190.0


async def test_background_loop_updates_and_stops():
    cache = PriceCache()
    source = SimulatorDataSource(cache, interval=0.01, engine=make_engine([]))
    await source.start(["AAPL"])
    await asyncio.sleep(0.1)
    await source.stop()
    version = cache.version
    assert version > 3
    await asyncio.sleep(0.05)
    assert cache.version == version  # no more ticks after stop
    await source.stop()  # idempotent
