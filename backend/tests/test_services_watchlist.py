import pytest

import db
from app.services.portfolio import execute_trade
from app.services.tickers import normalize_ticker, sync_tracked_tickers
from app.services.watchlist import (
    WatchlistError,
    add_ticker,
    get_watchlist_with_prices,
    remove_ticker,
)
from tests.conftest import NEW_TICKER_PRICE


@pytest.fixture(autouse=True)
def _db(db_path):
    return db_path


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("aapl", "AAPL"),
        (" brk.b ", "BRK.B"),
        ("A", "A"),
        ("", None),
        ("1ABC", None),
        ("AB-C", None),
        ("ABCDEFGHIJK", None),
        (None, None),
        (42, None),
    ],
)
def test_normalize_ticker(raw, expected):
    assert normalize_ticker(raw) == expected


def test_watchlist_with_prices(price_cache):
    price_cache.set("AAPL", 191.0)
    items = get_watchlist_with_prices(price_cache)
    assert [i["ticker"] for i in items] == [
        "AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX",
    ]
    assert items[0] == {
        "ticker": "AAPL",
        "price": 191.0,
        "previous_price": 190.0,
        "change_pct": pytest.approx(0.53),
        "direction": "up",
    }


def test_watchlist_item_without_price(price_cache):
    price_cache.remove("AAPL")
    item = get_watchlist_with_prices(price_cache)[0]
    assert item == {"ticker": "AAPL", "price": None, "previous_price": None, "change_pct": None, "direction": None}


async def test_add_ticker_starts_streaming(price_cache, market_source):
    item = await add_ticker(" pypl ", price_cache, market_source)
    assert item["ticker"] == "PYPL"
    assert item["price"] == NEW_TICKER_PRICE
    assert "PYPL" in market_source.get_tickers()
    assert db.get_watchlist()[-1]["ticker"] == "PYPL"


async def test_add_duplicate_is_409(price_cache, market_source):
    with pytest.raises(WatchlistError) as exc:
        await add_ticker("aapl", price_cache, market_source)
    assert exc.value.status_code == 409
    assert "already" in str(exc.value)


async def test_add_invalid_is_400(price_cache, market_source):
    with pytest.raises(WatchlistError) as exc:
        await add_ticker("not a ticker", price_cache, market_source)
    assert exc.value.status_code == 400


async def test_remove_ticker_stops_streaming(price_cache, market_source):
    result = await remove_ticker("nflx", price_cache, market_source)
    assert result == {"ticker": "NFLX"}
    assert "NFLX" not in market_source.get_tickers()
    assert price_cache.get("NFLX") is None
    assert "NFLX" not in [r["ticker"] for r in db.get_watchlist()]


async def test_remove_held_ticker_keeps_streaming(price_cache, market_source):
    execute_trade("AAPL", "buy", 1, price_cache)
    await remove_ticker("AAPL", price_cache, market_source)
    assert "AAPL" in market_source.get_tickers()
    assert price_cache.get_price("AAPL") == 190.0


async def test_remove_missing_is_404(price_cache, market_source):
    with pytest.raises(WatchlistError) as exc:
        await remove_ticker("PYPL", price_cache, market_source)
    assert exc.value.status_code == 404


async def test_sync_tracked_tickers(price_cache, market_source):
    # Held but unwatched ticker: still tracked until the position is closed.
    execute_trade("AAPL", "buy", 1, price_cache)
    await remove_ticker("AAPL", price_cache, market_source)
    execute_trade("AAPL", "sell", 1, price_cache)
    await sync_tracked_tickers(price_cache, market_source)
    assert "AAPL" not in market_source.get_tickers()

    # Missing tickers are (re)added.
    market_source.tickers.discard("MSFT")
    await sync_tracked_tickers(price_cache, market_source)
    assert "MSFT" in market_source.get_tickers()
