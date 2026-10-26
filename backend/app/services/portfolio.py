"""Portfolio valuation, trade execution and snapshots."""

import math

import db

from app.services.tickers import DEFAULT_USER_ID, normalize_ticker

# Quantities below this are treated as zero (float dust from fractional sells).
QTY_EPSILON = 1e-9
# Tolerance when comparing cash, so rounding never blocks spending your exact balance.
CASH_EPSILON = 1e-6


class TradeError(Exception):
    """A trade failed validation; the message is user-facing."""


def _money(value: float) -> float:
    return round(value, 2)


def _summarize(price_cache, user_id: str, conn=None) -> dict:
    cash = db.get_cash_balance(user_id, conn=conn)
    rows = db.get_positions(user_id, conn=conn)

    positions = []
    for row in rows:
        quantity = row["quantity"]
        avg_cost = row["avg_cost"]
        price = price_cache.get_price(row["ticker"])
        if price is None:
            price = avg_cost
        cost_basis = quantity * avg_cost
        market_value = quantity * price
        pnl = market_value - cost_basis
        positions.append(
            {
                "ticker": row["ticker"],
                "quantity": quantity,
                "avg_cost": round(avg_cost, 4),
                "current_price": price,
                "market_value": market_value,
                "unrealized_pnl": pnl,
                "unrealized_pnl_pct": (pnl / cost_basis * 100) if cost_basis else 0.0,
                "cost_basis": cost_basis,
            }
        )

    positions_value = sum(p["market_value"] for p in positions)
    cost_total = sum(p.pop("cost_basis") for p in positions)
    unrealized = positions_value - cost_total

    for p in positions:
        p["weight"] = round(p["market_value"] / positions_value * 100, 2) if positions_value else 0.0
        p["market_value"] = _money(p["market_value"])
        p["unrealized_pnl"] = _money(p["unrealized_pnl"])
        p["unrealized_pnl_pct"] = round(p["unrealized_pnl_pct"], 2)
    positions.sort(key=lambda p: p["market_value"], reverse=True)

    return {
        "cash_balance": _money(cash),
        "positions_value": _money(positions_value),
        "total_value": _money(cash + positions_value),
        "unrealized_pnl": _money(unrealized),
        "unrealized_pnl_pct": round(unrealized / cost_total * 100, 2) if cost_total else 0.0,
        "positions": positions,
    }


def get_portfolio_summary(price_cache, user_id: str = DEFAULT_USER_ID) -> dict:
    """Cash, positions valued at live prices, totals and P&L (GET /api/portfolio shape)."""
    return _summarize(price_cache, user_id)


def record_snapshot(price_cache, user_id: str = DEFAULT_USER_ID, conn=None) -> dict:
    """Store the current total portfolio value for the P&L chart."""
    total = _summarize(price_cache, user_id, conn=conn)["total_value"]
    return db.insert_snapshot(total, user_id, conn=conn)


def _validate(ticker, side, quantity) -> tuple[str, str, float]:
    symbol = normalize_ticker(ticker)
    if symbol is None:
        raise TradeError(f"Invalid ticker: {ticker!r}")
    side_norm = side.strip().lower() if isinstance(side, str) else None
    if side_norm not in ("buy", "sell"):
        raise TradeError(f"Invalid side: {side!r} (must be 'buy' or 'sell')")
    if isinstance(quantity, bool):
        raise TradeError("Quantity must be a number")
    try:
        qty = float(quantity)
    except (TypeError, ValueError):
        raise TradeError(f"Invalid quantity: {quantity!r}") from None
    if not math.isfinite(qty) or qty <= 0:
        raise TradeError("Quantity must be greater than zero")
    return symbol, side_norm, qty


def execute_trade(
    ticker: str, side: str, quantity: float, price_cache, user_id: str = DEFAULT_USER_ID
) -> dict:
    """Execute a market order at the current cached price.

    Updates cash and the position, logs the trade and records a snapshot, all in one
    transaction. Returns the trade row. Raises TradeError on any validation failure.
    """
    symbol, side, qty = _validate(ticker, side, quantity)

    price = price_cache.get_price(symbol)
    if price is None or price <= 0:
        raise TradeError(f"No price available for {symbol}. Add it to the watchlist first.")

    with db.transaction() as conn:
        cash = db.get_cash_balance(user_id, conn=conn)
        position = db.get_position(symbol, user_id, conn=conn)
        held = position["quantity"] if position else 0.0
        notional = qty * price

        if side == "buy":
            if notional > cash + CASH_EPSILON:
                raise TradeError(
                    f"Insufficient cash: need ${notional:,.2f}, have ${cash:,.2f}"
                )
            new_qty = held + qty
            new_avg = ((held * position["avg_cost"]) + notional) / new_qty if position else price
            db.set_cash_balance(max(cash - notional, 0.0), user_id, conn=conn)
            db.upsert_position(symbol, new_qty, new_avg, user_id, conn=conn)
        else:
            if held <= QTY_EPSILON:
                raise TradeError(f"You don't own any {symbol}")
            if qty > held + QTY_EPSILON:
                raise TradeError(
                    f"Insufficient shares: trying to sell {qty:g} {symbol}, you own {held:g}"
                )
            qty = min(qty, held)
            notional = qty * price
            remaining = held - qty
            db.set_cash_balance(cash + notional, user_id, conn=conn)
            if remaining <= QTY_EPSILON:
                db.delete_position(symbol, user_id, conn=conn)
            else:
                db.upsert_position(symbol, remaining, position["avg_cost"], user_id, conn=conn)

        trade = db.insert_trade(symbol, side, qty, price, user_id, conn=conn)
        record_snapshot(price_cache, user_id, conn=conn)

    return {
        "id": trade["id"],
        "ticker": trade["ticker"],
        "side": trade["side"],
        "quantity": trade["quantity"],
        "price": trade["price"],
        "executed_at": trade["executed_at"],
    }
