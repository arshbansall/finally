"""Both market data sources conform to MarketDataSource and the factory picks correctly."""

import inspect

import httpx
import pytest

from market import (
    FallbackDataSource,
    MarketDataSource,
    MassiveDataSource,
    PriceCache,
    SimulatorDataSource,
    create_market_data_source,
)

ASYNC_METHODS = ["start", "stop", "add_ticker", "remove_ticker"]


def test_interface_is_abstract():
    with pytest.raises(TypeError):
        MarketDataSource()  # type: ignore[abstract]


@pytest.mark.parametrize("cls", [SimulatorDataSource, MassiveDataSource, FallbackDataSource])
def test_implementations_conform(cls):
    assert issubclass(cls, MarketDataSource)
    assert not inspect.isabstract(cls)
    for name in ASYNC_METHODS:
        assert inspect.iscoroutinefunction(getattr(cls, name)), name
    assert not inspect.iscoroutinefunction(cls.get_tickers)


def _massive_with_mock_client(cache: PriceCache) -> MassiveDataSource:
    def handler(request: httpx.Request) -> httpx.Response:
        tickers = request.url.params["tickers"].split(",")
        return httpx.Response(
            200,
            json={"status": "OK", "tickers": [{"ticker": t, "lastTrade": {"p": 100.0}} for t in tickers]},
        )

    client = httpx.AsyncClient(base_url="https://api.massive.test", transport=httpx.MockTransport(handler))
    return MassiveDataSource(cache, "k", poll_interval=60, client=client)


def _make_source(kind: str, cache: PriceCache) -> MarketDataSource:
    if kind == "simulator":
        return SimulatorDataSource(cache, interval=60)
    if kind == "massive":
        return _massive_with_mock_client(cache)
    return FallbackDataSource(_massive_with_mock_client(cache), lambda: SimulatorDataSource(cache, interval=60))


@pytest.mark.parametrize("kind", ["simulator", "massive", "fallback"])
async def test_lifecycle_behaves_the_same(kind):
    cache = PriceCache()
    source = _make_source(kind, cache)

    await source.start(["AAPL", "msft"])
    try:
        assert sorted(source.get_tickers()) == ["AAPL", "MSFT"]
        await source.add_ticker("NVDA")
        await source.add_ticker("nvda")
        assert sorted(source.get_tickers()) == ["AAPL", "MSFT", "NVDA"]
        await source.remove_ticker("msft")
        assert sorted(source.get_tickers()) == ["AAPL", "NVDA"]
        assert cache.get("MSFT") is None
        await source.remove_ticker("UNKNOWN")  # no error
    finally:
        await source.stop()
        await source.stop()


def test_factory_defaults_to_simulator(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)


@pytest.mark.parametrize("value", ["", "   "])
def test_factory_blank_key_uses_simulator(monkeypatch, value):
    monkeypatch.setenv("MASSIVE_API_KEY", value)
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)


def test_factory_uses_massive_when_key_set(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "abc123")
    monkeypatch.delenv("MASSIVE_POLL_INTERVAL", raising=False)
    cache = PriceCache()
    source = create_market_data_source(cache)
    assert isinstance(source, FallbackDataSource)
    assert isinstance(source.primary, MassiveDataSource)
    assert source.active is source.primary
    assert source.primary.api_key == "abc123"
    assert source.primary.poll_interval == 15.0
    assert source.primary.cache is cache
    fallback = source._fallback_factory()
    assert isinstance(fallback, SimulatorDataSource)
    assert fallback.cache is cache


@pytest.mark.parametrize("raw,expected", [("5", 5.0), ("2.5", 2.5), ("bad", 15.0), ("0", 15.0), ("-3", 15.0)])
def test_factory_poll_interval(monkeypatch, raw, expected):
    monkeypatch.setenv("MASSIVE_API_KEY", "abc123")
    monkeypatch.setenv("MASSIVE_POLL_INTERVAL", raw)
    assert create_market_data_source(PriceCache()).primary.poll_interval == expected
