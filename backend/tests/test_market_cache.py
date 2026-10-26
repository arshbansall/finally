import threading

import pytest

from market import PriceCache, PriceUpdate


def test_first_update_is_flat_and_sets_open_price():
    cache = PriceCache()
    update = cache.update("aapl", 190.0, "2026-10-26T15:00:00.000+00:00")

    assert update == PriceUpdate(
        ticker="AAPL",
        price=190.0,
        previous_price=190.0,
        open_price=190.0,
        timestamp="2026-10-26T15:00:00.000+00:00",
        direction="flat",
        change=0.0,
        change_pct=0.0,
    )
    assert cache.get("AAPL") == update
    assert cache.get("aapl") == update


def test_direction_previous_price_and_change():
    cache = PriceCache()
    cache.update("AAPL", 100.0)

    up = cache.update("AAPL", 101.5)
    assert (up.direction, up.previous_price, up.open_price) == ("up", 100.0, 100.0)
    assert up.change == 1.5
    assert up.change_pct == 1.5

    down = cache.update("AAPL", 99.0)
    assert (down.direction, down.previous_price, down.open_price) == ("down", 101.5, 100.0)
    assert down.change == -1.0
    assert down.change_pct == -1.0

    flat = cache.update("AAPL", 99.0)
    assert flat.direction == "flat"
    assert flat.previous_price == 99.0


def test_explicit_open_price_overrides_session_open():
    cache = PriceCache()
    update = cache.update("AAPL", 102.0, open_price=100.0)
    assert update.open_price == 100.0
    assert update.change_pct == 2.0
    # Later updates without open_price keep the reference.
    assert cache.update("AAPL", 103.0).open_price == 100.0


def test_prices_are_rounded_and_no_negative_zero():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    update = cache.update("AAPL", 189.999)
    assert update.price == 190.0
    assert str(update.change_pct) == "0.0"
    tiny = cache.update("AAPL", 189.99)
    assert tiny.change_pct == pytest.approx(-0.01, abs=0.01)


def test_rejects_non_positive_price():
    cache = PriceCache()
    with pytest.raises(ValueError):
        cache.update("AAPL", 0)
    assert cache.get("AAPL") is None
    assert cache.version == 0


def test_version_increments_on_update_and_remove():
    cache = PriceCache()
    assert cache.version == 0
    cache.update("AAPL", 1.0)
    cache.update("AAPL", 2.0)
    assert cache.version == 2
    cache.remove("AAPL")
    assert cache.version == 3
    cache.remove("AAPL")  # no-op
    assert cache.version == 3


def test_get_price_get_all_remove():
    cache = PriceCache()
    assert cache.get_price("AAPL") is None
    cache.update("AAPL", 190.0)
    cache.update("MSFT", 420.0)
    assert cache.get_price("AAPL") == 190.0
    assert set(cache.get_all()) == {"AAPL", "MSFT"}
    assert "msft" in cache and len(cache) == 2

    snapshot = cache.get_all()
    cache.remove("msft")
    assert "MSFT" in snapshot  # get_all returns a copy
    assert cache.get("MSFT") is None


def test_to_dict_matches_contract_keys():
    update = PriceCache().update("AAPL", 190.0)
    assert set(update.to_dict()) == {
        "ticker", "price", "previous_price", "open_price",
        "timestamp", "direction", "change", "change_pct",
    }


def test_concurrent_updates_are_consistent():
    cache = PriceCache()

    def writer(n: int) -> None:
        for i in range(500):
            cache.update(f"T{n}", 100.0 + i)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert cache.version == 8 * 500
    assert all(cache.get_price(f"T{n}") == 599.0 for n in range(8))
