import asyncio
import copy

import httpx
import pytest

from market import MassiveDataSource, PriceCache
from market.massive import (
    SNAPSHOT_PATH,
    SnapshotQuote,
    parse_snapshot_item,
    parse_snapshot_response,
)

# Verbatim sample from the Massive docs (GET /v2/snapshot/locale/us/markets/stocks/tickers).
DOCS_SAMPLE = {
    "count": 1,
    "status": "OK",
    "tickers": [
        {
            "day": {"c": 20.506, "dv": "37216.0", "h": 20.64, "l": 20.506, "o": 20.64, "v": 37216, "vw": 20.616},
            "lastQuote": {"P": 20.6, "S": 22, "p": 20.5, "s": 13, "t": 1605192959994246100},
            "lastTrade": {
                "c": [14, 41], "ds": "2416.0", "i": "71675577320245",
                "p": 20.506, "s": 2416, "t": 1605192894630916600, "x": 4,
            },
            "min": {
                "av": 37216, "c": 20.506, "dav": "37216.0", "dv": "5000.0", "h": 20.506,
                "l": 20.506, "n": 1, "o": 20.506, "t": 1684428600000, "v": 5000, "vw": 20.5105,
            },
            "prevDay": {"c": 20.63, "h": 21, "l": 20.5, "o": 20.79, "v": 292738, "vw": 20.6939},
            "ticker": "BCAT",
            "todaysChange": -0.124,
            "todaysChangePerc": -0.601,
            "updated": 1605192894630916600,
        }
    ],
}


def snapshot_item(ticker: str, price: float, prev_close: float, trade_ts: int = 1761490800123456789) -> dict:
    item = copy.deepcopy(DOCS_SAMPLE["tickers"][0])
    item["ticker"] = ticker
    item["lastTrade"]["p"] = price
    item["lastTrade"]["t"] = trade_ts
    item["prevDay"]["c"] = prev_close
    return item


# --- parsing ---------------------------------------------------------------


def test_parse_docs_sample():
    quotes = parse_snapshot_response(DOCS_SAMPLE)
    assert quotes == [
        SnapshotQuote(
            ticker="BCAT",
            price=20.506,
            open_price=20.63,
            timestamp="2020-11-12T14:54:54.630+00:00",
        )
    ]


def test_change_pct_matches_massive_todays_change():
    quote = parse_snapshot_response(DOCS_SAMPLE)[0]
    update = PriceCache().update(quote.ticker, quote.price, quote.timestamp, open_price=quote.open_price)
    assert update.change_pct == pytest.approx(DOCS_SAMPLE["tickers"][0]["todaysChangePerc"], abs=0.05)


def test_price_falls_back_without_last_trade():
    item = copy.deepcopy(DOCS_SAMPLE["tickers"][0])
    del item["lastTrade"]  # plan without trades
    item["min"]["c"] = 20.55
    quote = parse_snapshot_item(item)
    assert quote.price == 20.55
    # timestamp falls back to "updated" (ns)
    assert quote.timestamp == "2020-11-12T14:54:54.630+00:00"


def test_pre_market_zero_day_bar_uses_previous_close():
    item = {
        "ticker": "AAPL",
        "day": {"c": 0, "h": 0, "l": 0, "o": 0, "v": 0, "vw": 0},
        "min": {},
        "prevDay": {"c": 189.5, "o": 188.0},
        "updated": 0,
    }
    quote = parse_snapshot_item(item)
    assert quote.price == 189.5
    assert quote.open_price == 189.5
    assert quote.timestamp is None


def test_open_price_falls_back_to_day_open():
    item = {"ticker": "AAPL", "day": {"o": 188.0, "c": 190.0}}
    assert parse_snapshot_item(item).open_price == 188.0


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "oops",
        {},
        {"status": "ERROR", "error": "Unknown API Key"},
        {"status": "OK", "tickers": None},
        {"status": "OK", "tickers": "AAPL"},
    ],
)
def test_malformed_payloads_return_empty(payload):
    assert parse_snapshot_response(payload) == []


def test_malformed_items_are_skipped():
    payload = {
        "status": "OK",
        "tickers": [
            "junk",
            {"no": "ticker"},
            {"ticker": "NOPRICE", "day": {"c": 0}, "prevDay": {}},
            {"ticker": "BAD", "lastTrade": {"p": "abc"}, "min": {"c": None}},
            {"ticker": "msft", "lastTrade": {"p": 420.12, "t": "garbage"}, "min": {"c": 420.0, "t": 1761490800000}},
        ],
    }
    quotes = parse_snapshot_response(payload)
    assert [q.ticker for q in quotes] == ["MSFT"]
    assert quotes[0].price == 420.12
    assert quotes[0].timestamp == "2025-10-26T15:00:00.000+00:00"  # from min.t (ms)


# --- polling ---------------------------------------------------------------


class FakeMassive:
    """httpx MockTransport handler recording requests and serving canned snapshots."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.prices: dict[str, float] = {"AAPL": 190.25, "MSFT": 420.5, "PYPL": 70.1}
        self.status_code = 200
        self.body: object | None = None
        self.raise_error: Exception | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raise_error:
            raise self.raise_error
        if self.status_code != 200:
            return httpx.Response(self.status_code, json={"status": "ERROR", "error": "nope"})
        if self.body is not None:
            return httpx.Response(200, content=self.body if isinstance(self.body, bytes) else None,
                                  json=None if isinstance(self.body, bytes) else self.body)
        wanted = request.url.params["tickers"].split(",")
        items = [snapshot_item(t, self.prices[t], self.prices[t] - 1) for t in wanted if t in self.prices]
        return httpx.Response(200, json={"status": "OK", "count": len(items), "tickers": items})


@pytest.fixture
def fake():
    return FakeMassive()


@pytest.fixture
async def client(fake):
    async with httpx.AsyncClient(
        base_url="https://api.massive.test",
        transport=httpx.MockTransport(fake),
        headers={"Authorization": "Bearer test-key"},
    ) as c:
        yield c


async def test_poll_once_updates_cache(fake, client):
    cache = PriceCache()
    source = MassiveDataSource(cache, "test-key", client=client)
    source._tickers = ["AAPL", "MSFT"]

    assert await source.poll_once() == 2
    request = fake.requests[0]
    assert request.url.path == SNAPSHOT_PATH
    assert request.url.params["tickers"] == "AAPL,MSFT"
    assert request.headers["Authorization"] == "Bearer test-key"

    aapl = cache.get("AAPL")
    assert aapl.price == 190.25
    assert aapl.open_price == 189.25
    assert aapl.timestamp == "2025-10-26T15:00:00.123+00:00"

    fake.prices["AAPL"] = 191.0
    await source.poll_once()
    aapl = cache.get("AAPL")
    assert (aapl.price, aapl.previous_price, aapl.direction) == (191.0, 190.25, "up")


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_http_errors_keep_last_prices(fake, client, status):
    cache = PriceCache()
    source = MassiveDataSource(cache, "test-key", client=client)
    source._tickers = ["AAPL"]
    await source.poll_once()
    version = cache.version

    fake.status_code = status
    assert await source.poll_once() == 0
    assert cache.get_price("AAPL") == 190.25
    assert cache.version == version


async def test_network_error_and_bad_json_are_tolerated(fake, client):
    cache = PriceCache()
    source = MassiveDataSource(cache, "test-key", client=client)
    source._tickers = ["AAPL"]

    fake.raise_error = httpx.ConnectError("boom")
    assert await source.poll_once() == 0

    fake.raise_error = None
    fake.body = b"<html>not json</html>"
    assert await source.poll_once() == 0
    assert cache.get("AAPL") is None


async def test_no_request_without_tickers(fake, client):
    source = MassiveDataSource(PriceCache(), "test-key", client=client)
    assert await source.poll_once() == 0
    assert fake.requests == []


async def test_start_add_remove_stop(fake, client):
    cache = PriceCache()
    source = MassiveDataSource(cache, "test-key", poll_interval=0.02, client=client)
    await source.start(["aapl", "MSFT"])
    try:
        await asyncio.sleep(0.01)
        assert cache.get_price("AAPL") == 190.25  # first poll happens immediately
        assert source.get_tickers() == ["AAPL", "MSFT"]

        await source.add_ticker("pypl")
        await asyncio.sleep(0.01)
        assert cache.get_price("PYPL") == 70.1
        assert any(r.url.params["tickers"] == "PYPL" for r in fake.requests)  # immediate fetch

        await source.remove_ticker("MSFT")
        assert cache.get("MSFT") is None
        await asyncio.sleep(0.05)
        assert cache.get("MSFT") is None  # not re-added by later polls
        assert "MSFT" not in fake.requests[-1].url.params["tickers"]
    finally:
        await source.stop()

    count = len(fake.requests)
    await asyncio.sleep(0.05)
    assert len(fake.requests) == count  # polling stopped
    assert not client.is_closed  # injected client is not closed by the source


async def test_ignores_tickers_not_tracked(fake, client):
    cache = PriceCache()
    source = MassiveDataSource(cache, "test-key", client=client)
    source._tickers = ["AAPL"]
    await source.poll_once(["AAPL", "MSFT"])
    assert cache.get("MSFT") is None


async def test_owned_client_is_created_and_closed(monkeypatch):
    source = MassiveDataSource(PriceCache(), "secret", poll_interval=60)
    monkeypatch.setattr(source, "poll_once", lambda tickers=None: asyncio.sleep(0, result=0))
    await source.start([])
    client = source._client
    assert client.headers["Authorization"] == "Bearer secret"
    assert str(client.base_url).startswith("https://api.massive.com")
    await source.stop()
    assert client.is_closed
