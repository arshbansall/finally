"""Massive -> simulator fallback when Massive can't supply prices at startup."""

import asyncio
import logging

import httpx
import pytest

from market import FallbackDataSource, MassiveDataSource, PriceCache, SimulatorDataSource

SIM_SEEDS = {"AAPL": 190.0, "MSFT": 420.0, "NFLX": 650.0}  # simulator seed prices


class ScriptedMassive:
    """MockTransport handler. ``mode``: "ok", "network", or an HTTP status code."""

    def __init__(self, mode="ok") -> None:
        self.mode = mode
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.mode == "network":
            raise httpx.ConnectError("connection refused")
        if self.mode == "not_authorized_body":
            return httpx.Response(200, json={"status": "NOT_AUTHORIZED", "message": "plan lacks snapshots"})
        if self.mode != "ok":
            return httpx.Response(self.mode, json={"status": "ERROR", "error": "nope"})
        tickers = request.url.params["tickers"].split(",")
        items = [{"ticker": t, "lastTrade": {"p": 100.0 + i}, "prevDay": {"c": 99.0}} for i, t in enumerate(tickers)]
        return httpx.Response(200, json={"status": "OK", "tickers": items})


async def eventually(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)


@pytest.fixture
def server():
    return ScriptedMassive()


@pytest.fixture
async def make_source(server):
    clients: list[httpx.AsyncClient] = []
    sources: list[FallbackDataSource] = []

    def factory(cache: PriceCache, sim_interval: float = 60.0) -> FallbackDataSource:
        client = httpx.AsyncClient(base_url="https://api.massive.test", transport=httpx.MockTransport(server))
        clients.append(client)
        massive = MassiveDataSource(
            cache, "key", poll_interval=0.02, client=client, startup_retry_interval=0.01
        )
        source = FallbackDataSource(massive, lambda: SimulatorDataSource(cache, interval=sim_interval))
        sources.append(source)
        return source

    yield factory
    for source in sources:
        await source.stop()
    for client in clients:
        await client.aclose()


def fallback_warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and "falling back" in r.getMessage()]


@pytest.mark.parametrize(
    "status,hint",
    [(401, "the key is invalid"), (403, "the snapshot endpoint needs a paid plan")],
)
async def test_auth_rejection_falls_back_immediately(server, make_source, caplog, status, hint):
    caplog.set_level(logging.WARNING)
    server.mode = status
    cache = PriceCache()
    source = make_source(cache)

    await source.start(["AAPL", "MSFT"])
    await eventually(lambda: source.using_fallback)

    assert len(server.requests) == 1  # one probe, no retries
    assert fallback_warnings(caplog) == [
        f"Massive API key rejected (HTTP {status}) — {hint}; falling back to the built-in simulator"
    ]
    assert isinstance(source.active, SimulatorDataSource)
    assert sorted(source.get_tickers()) == ["AAPL", "MSFT"]
    # Simulator seeded the cache (it may already have ticked once).
    assert {t: cache.get(t).open_price for t in ("AAPL", "MSFT")} == {"AAPL": 190.0, "MSFT": 420.0}

    await asyncio.sleep(0.1)
    assert len(server.requests) == 1  # Massive no longer polled


async def test_repeated_network_errors_at_startup_fall_back(server, make_source, caplog):
    caplog.set_level(logging.WARNING)
    server.mode = "network"
    cache = PriceCache()
    source = make_source(cache)

    await source.start(["AAPL"])
    await eventually(lambda: source.using_fallback)

    assert len(server.requests) == 3
    [warning] = fallback_warnings(caplog)
    assert "no successful snapshot after 3 attempts" in warning
    assert "connection refused" in warning
    assert cache.get("AAPL").open_price == 190.0


@pytest.mark.parametrize("mode", [500, 503, 429, "not_authorized_body"])
async def test_repeated_other_failures_at_startup_fall_back(server, make_source, mode):
    server.mode = mode
    source = make_source(PriceCache())
    await source.start(["AAPL"])
    await eventually(lambda: source.using_fallback)
    assert len(server.requests) == 3


async def test_transient_startup_error_then_success_does_not_fall_back(server, make_source):
    server.mode = "network"
    cache = PriceCache()
    source = make_source(cache)
    await source.start(["AAPL"])
    await eventually(lambda: len(server.requests) >= 2)
    server.mode = "ok"
    await eventually(lambda: cache.get_price("AAPL") == 100.0)
    assert not source.using_fallback


@pytest.mark.parametrize("mode", [500, "network", 401, 403, 429])
async def test_errors_after_success_keep_last_prices(server, make_source, caplog, mode):
    caplog.set_level(logging.WARNING)
    cache = PriceCache()
    source = make_source(cache)
    await source.start(["AAPL"])
    await eventually(lambda: cache.get_price("AAPL") == 100.0)

    server.mode = mode
    seen = len(server.requests)
    await eventually(lambda: len(server.requests) >= seen + 5)

    assert not source.using_fallback
    assert source.active is source.primary
    assert cache.get_price("AAPL") == 100.0
    assert fallback_warnings(caplog) == []


async def test_ticker_added_before_switch_gets_simulated_price(server, make_source):
    server.mode = "network"
    cache = PriceCache()
    source = make_source(cache)
    await source.start(["AAPL"])
    await source.add_ticker("pypl")  # Massive still active
    await source.remove_ticker("AAPL")
    assert not source.using_fallback

    await eventually(lambda: source.using_fallback)
    assert source.get_tickers() == ["PYPL"]
    assert cache.get_price("PYPL") > 0
    assert cache.get("AAPL") is None


async def test_ticker_changes_after_switch_reach_simulator(server, make_source):
    server.mode = 403
    cache = PriceCache()
    source = make_source(cache)
    await source.start(["AAPL"])
    await eventually(lambda: source.using_fallback)

    await source.add_ticker("nflx")
    assert cache.get_price("NFLX") == SIM_SEEDS["NFLX"]  # immediately, no wait for the next tick
    assert sorted(source.get_tickers()) == ["AAPL", "NFLX"]
    assert sorted(source.fallback.get_tickers()) == ["AAPL", "NFLX"]

    await source.remove_ticker("AAPL")
    assert source.get_tickers() == ["NFLX"]
    assert cache.get("AAPL") is None
    assert len(server.requests) == 1  # Massive never called again


async def test_ticker_change_racing_the_switch_is_not_lost(server, make_source):
    server.mode = 401
    cache = PriceCache()
    source = make_source(cache)
    await source.start(["AAPL"])
    await eventually(lambda: source._switch_task is not None)
    # Switch is scheduled but may not have run; the change must land either way.
    await source.add_ticker("MSFT")
    await source.wait_for_switch()
    assert sorted(source.get_tickers()) == ["AAPL", "MSFT"]
    assert cache.get("MSFT").open_price == 420.0


async def test_simulator_keeps_ticking_after_switch_and_stop_halts_it(server, make_source):
    server.mode = 403
    cache = PriceCache()
    source = make_source(cache, sim_interval=0.01)
    await source.start(["AAPL"])
    await eventually(lambda: source.using_fallback)
    version = cache.version
    await eventually(lambda: cache.version > version + 3)

    await source.stop()
    version = cache.version
    await asyncio.sleep(0.05)
    assert cache.version == version
    await source.stop()  # idempotent


async def test_stop_before_switch_runs_starts_no_simulator(server, make_source):
    server.mode = "network"
    cache = PriceCache()
    source = make_source(cache, sim_interval=0.01)
    await source.start(["AAPL"])
    source._on_primary_unavailable("Massive API key rejected (HTTP 401)")  # as the poller would
    assert source._switch_task is not None and not source._switch_task.done()
    await source.stop()
    assert not source.using_fallback
    await asyncio.sleep(0.05)
    assert cache.get("AAPL") is None


async def test_stop_in_massive_mode(server, make_source):
    cache = PriceCache()
    source = make_source(cache)
    await source.start(["AAPL"])
    await eventually(lambda: cache.get_price("AAPL") == 100.0)
    await source.stop()
    count = len(server.requests)
    await asyncio.sleep(0.05)
    assert len(server.requests) == count
    assert not source.using_fallback


async def test_standalone_massive_stops_polling_when_unavailable(server, caplog):
    server.mode = 403
    async with httpx.AsyncClient(base_url="https://api.massive.test", transport=httpx.MockTransport(server)) as client:
        source = MassiveDataSource(PriceCache(), "key", poll_interval=0.01, client=client)
        await source.start(["AAPL"])
        await eventually(lambda: source.unavailable_reason is not None)
        await asyncio.sleep(0.05)
        assert len(server.requests) == 1
        assert "HTTP 403" in source.unavailable_reason
        assert any(r.levelno == logging.ERROR and "polling stopped" in r.getMessage() for r in caplog.records)
        await source.stop()
