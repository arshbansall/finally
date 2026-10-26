import pytest

import db
from app.services.portfolio import (
    TradeError,
    execute_trade,
    get_portfolio_summary,
    record_snapshot,
)


@pytest.fixture(autouse=True)
def _db(db_path):
    return db_path


def test_fresh_portfolio(price_cache):
    summary = get_portfolio_summary(price_cache)
    assert summary == {
        "cash_balance": 10000.0,
        "positions_value": 0.0,
        "total_value": 10000.0,
        "unrealized_pnl": 0.0,
        "unrealized_pnl_pct": 0.0,
        "positions": [],
    }


def test_buy_creates_position_and_debits_cash(price_cache):
    trade = execute_trade("aapl", "buy", 10, price_cache)
    assert trade["ticker"] == "AAPL"
    assert trade["side"] == "buy"
    assert trade["quantity"] == 10
    assert trade["price"] == 190.0
    assert set(trade) == {"id", "ticker", "side", "quantity", "price", "executed_at"}

    assert db.get_cash_balance() == pytest.approx(8100.0)
    position = db.get_position("AAPL")
    assert position["quantity"] == 10
    assert position["avg_cost"] == 190.0
    assert len(db.get_trades()) == 1


def test_buy_twice_uses_weighted_average_cost(price_cache):
    execute_trade("AAPL", "buy", 10, price_cache)
    price_cache.set("AAPL", 200.0)
    execute_trade("AAPL", "buy", 30, price_cache)
    position = db.get_position("AAPL")
    assert position["quantity"] == 40
    assert position["avg_cost"] == pytest.approx((10 * 190 + 30 * 200) / 40)
    assert db.get_cash_balance() == pytest.approx(10000 - 1900 - 6000)


def test_fractional_shares(price_cache):
    execute_trade("NVDA", "buy", 0.5, price_cache)
    execute_trade("NVDA", "sell", 0.2, price_cache)
    assert db.get_position("NVDA")["quantity"] == pytest.approx(0.3)
    assert db.get_cash_balance() == pytest.approx(10000 - 0.3 * 120)


def test_fractional_sell_to_zero_removes_position(price_cache):
    execute_trade("NVDA", "buy", 0.3, price_cache)
    execute_trade("NVDA", "sell", 0.1, price_cache)
    execute_trade("NVDA", "sell", 0.2, price_cache)  # float dust must not leave a position
    assert db.get_position("NVDA") is None


def test_partial_sell_keeps_avg_cost(price_cache):
    execute_trade("AAPL", "buy", 10, price_cache)
    price_cache.set("AAPL", 210.0)
    execute_trade("AAPL", "sell", 4, price_cache)
    position = db.get_position("AAPL")
    assert position["quantity"] == 6
    assert position["avg_cost"] == 190.0
    assert db.get_cash_balance() == pytest.approx(10000 - 1900 + 4 * 210)


def test_sell_to_zero_deletes_position(price_cache):
    execute_trade("AAPL", "buy", 10, price_cache)
    execute_trade("AAPL", "sell", 10, price_cache)
    assert db.get_position("AAPL") is None
    assert db.get_cash_balance() == pytest.approx(10000.0)
    assert [t["side"] for t in db.get_trades()] == ["sell", "buy"]


def test_sell_at_a_loss(price_cache):
    execute_trade("TSLA", "buy", 10, price_cache)
    price_cache.set("TSLA", 200.0)
    summary = get_portfolio_summary(price_cache)
    assert summary["unrealized_pnl"] == pytest.approx(-500.0)
    execute_trade("TSLA", "sell", 10, price_cache)
    assert db.get_cash_balance() == pytest.approx(10000 - 500)
    assert get_portfolio_summary(price_cache)["positions"] == []


def test_sell_more_than_owned_fails_without_changes(price_cache):
    execute_trade("AAPL", "buy", 5, price_cache)
    with pytest.raises(TradeError, match="Insufficient shares"):
        execute_trade("AAPL", "sell", 6, price_cache)
    assert db.get_position("AAPL")["quantity"] == 5
    assert db.get_cash_balance() == pytest.approx(10000 - 950)
    assert len(db.get_trades()) == 1


def test_sell_unowned_fails(price_cache):
    with pytest.raises(TradeError, match="don't own any MSFT"):
        execute_trade("MSFT", "sell", 1, price_cache)


def test_insufficient_cash_fails_without_changes(price_cache):
    with pytest.raises(TradeError, match=r"Insufficient cash: need \$11,400.00, have \$10,000.00"):
        execute_trade("AAPL", "buy", 60, price_cache)
    assert db.get_cash_balance() == 10000.0
    assert db.get_positions() == []
    assert db.get_trades() == []


def test_can_spend_exact_cash_balance(price_cache):
    price_cache.set("AAPL", 200.0)
    execute_trade("AAPL", "buy", 50, price_cache)
    assert db.get_cash_balance() == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("ticker", "side", "quantity", "match"),
    [
        ("", "buy", 1, "Invalid ticker"),
        ("123", "buy", 1, "Invalid ticker"),
        ("TOOLONGTICKER", "buy", 1, "Invalid ticker"),
        ("AAPL", "short", 1, "Invalid side"),
        ("AAPL", "buy", 0, "greater than zero"),
        ("AAPL", "buy", -3, "greater than zero"),
        ("AAPL", "buy", float("nan"), "greater than zero"),
        ("AAPL", "buy", float("inf"), "greater than zero"),
        ("AAPL", "buy", "abc", "Invalid quantity"),
        ("AAPL", "buy", True, "must be a number"),
    ],
)
def test_validation_errors(price_cache, ticker, side, quantity, match):
    with pytest.raises(TradeError, match=match):
        execute_trade(ticker, side, quantity, price_cache)


def test_side_is_case_insensitive(price_cache):
    assert execute_trade("AAPL", " BUY ", 1, price_cache)["side"] == "buy"


def test_no_price_available(price_cache):
    with pytest.raises(TradeError, match="No price available for PYPL"):
        execute_trade("PYPL", "buy", 1, price_cache)


def test_trade_records_snapshot(price_cache):
    before = len(db.get_snapshots())
    execute_trade("AAPL", "buy", 10, price_cache)
    snapshots = db.get_snapshots()
    assert len(snapshots) == before + 1
    assert snapshots[-1]["total_value"] == pytest.approx(10000.0)


def test_failed_trade_records_no_snapshot(price_cache):
    with pytest.raises(TradeError):
        execute_trade("AAPL", "buy", 1000, price_cache)
    assert db.get_snapshots() == []


def test_summary_values_weights_and_pnl(price_cache):
    execute_trade("AAPL", "buy", 10, price_cache)  # 1900
    execute_trade("MSFT", "buy", 5, price_cache)  # 2100
    price_cache.set("AAPL", 200.0)  # +100
    price_cache.set("MSFT", 400.0)  # -100

    summary = get_portfolio_summary(price_cache)
    assert summary["cash_balance"] == pytest.approx(6000.0)
    assert summary["positions_value"] == pytest.approx(4000.0)
    assert summary["total_value"] == pytest.approx(10000.0)
    assert summary["unrealized_pnl"] == pytest.approx(0.0)
    assert summary["unrealized_pnl_pct"] == pytest.approx(0.0)

    by_ticker = {p["ticker"]: p for p in summary["positions"]}
    aapl = by_ticker["AAPL"]
    assert aapl == {
        "ticker": "AAPL",
        "quantity": 10,
        "avg_cost": 190.0,
        "current_price": 200.0,
        "market_value": 2000.0,
        "unrealized_pnl": 100.0,
        "unrealized_pnl_pct": pytest.approx(5.26),
        "weight": 50.0,
    }
    assert by_ticker["MSFT"]["unrealized_pnl"] == pytest.approx(-100.0)
    assert by_ticker["MSFT"]["unrealized_pnl_pct"] == pytest.approx(-4.76)
    assert sum(p["weight"] for p in summary["positions"]) == pytest.approx(100.0)


def test_summary_falls_back_to_avg_cost_without_price(price_cache):
    execute_trade("AAPL", "buy", 10, price_cache)
    price_cache.remove("AAPL")
    position = get_portfolio_summary(price_cache)["positions"][0]
    assert position["current_price"] == 190.0
    assert position["unrealized_pnl"] == 0.0


def test_record_snapshot(price_cache):
    execute_trade("AAPL", "buy", 10, price_cache)
    price_cache.set("AAPL", 200.0)
    snap = record_snapshot(price_cache)
    assert snap["total_value"] == pytest.approx(10100.0)
    assert db.get_snapshots()[-1]["id"] == snap["id"]
