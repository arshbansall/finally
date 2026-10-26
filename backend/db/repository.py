"""Repository functions: plain-dict access to every table.

Functions that accept `conn` run on the caller's connection (e.g. inside `transaction()`) when given;
otherwise each call uses its own short-lived, autocommitting connection.
"""

from __future__ import annotations

import json
import sqlite3

from .connection import DEFAULT_USER_ID, new_id, now_iso, use_connection


def _norm(ticker: str) -> str:
    return ticker.strip().upper()


# --- users_profile ---------------------------------------------------------------------------------


def get_cash_balance(user_id: str = DEFAULT_USER_ID, conn: sqlite3.Connection | None = None) -> float:
    """Cash balance for the user, 0.0 if the user has no profile row."""
    with use_connection(conn) as c:
        row = c.execute("SELECT cash_balance FROM users_profile WHERE id = ?", (user_id,)).fetchone()
    return float(row["cash_balance"]) if row else 0.0


def set_cash_balance(
    amount: float, user_id: str = DEFAULT_USER_ID, conn: sqlite3.Connection | None = None
) -> None:
    """Set the cash balance, creating the profile row if needed."""
    with use_connection(conn) as c:
        c.execute(
            "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET cash_balance = excluded.cash_balance",
            (user_id, float(amount), now_iso()),
        )


# --- watchlist -------------------------------------------------------------------------------------


def get_watchlist(user_id: str = DEFAULT_USER_ID) -> list[dict]:
    """[{id, ticker, added_at}] in the order tickers were added."""
    with use_connection(None) as c:
        rows = c.execute(
            "SELECT id, ticker, added_at FROM watchlist WHERE user_id = ? ORDER BY added_at, rowid",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_watchlist_ticker(ticker: str, user_id: str = DEFAULT_USER_ID) -> bool:
    """Add a ticker; False if it is already on the watchlist."""
    with use_connection(None) as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
            (new_id(), user_id, _norm(ticker), now_iso()),
        )
    return cur.rowcount == 1


def remove_watchlist_ticker(ticker: str, user_id: str = DEFAULT_USER_ID) -> bool:
    """Remove a ticker; False if it was not on the watchlist."""
    with use_connection(None) as c:
        cur = c.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?", (user_id, _norm(ticker))
        )
    return cur.rowcount > 0


# --- positions -------------------------------------------------------------------------------------

_POSITION_COLS = "id, ticker, quantity, avg_cost, updated_at"


def get_positions(user_id: str = DEFAULT_USER_ID, conn: sqlite3.Connection | None = None) -> list[dict]:
    """[{id, ticker, quantity, avg_cost, updated_at}] ordered by ticker."""
    with use_connection(conn) as c:
        rows = c.execute(
            f"SELECT {_POSITION_COLS} FROM positions WHERE user_id = ? ORDER BY ticker", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_position(
    ticker: str, user_id: str = DEFAULT_USER_ID, conn: sqlite3.Connection | None = None
) -> dict | None:
    with use_connection(conn) as c:
        row = c.execute(
            f"SELECT {_POSITION_COLS} FROM positions WHERE user_id = ? AND ticker = ?",
            (user_id, _norm(ticker)),
        ).fetchone()
    return dict(row) if row else None


def upsert_position(
    ticker: str,
    quantity: float,
    avg_cost: float,
    user_id: str = DEFAULT_USER_ID,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Insert or overwrite the position's quantity and avg_cost (the row id is kept on update)."""
    with use_connection(conn) as c:
        c.execute(
            "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (user_id, ticker) DO UPDATE SET "
            "quantity = excluded.quantity, avg_cost = excluded.avg_cost, updated_at = excluded.updated_at",
            (new_id(), user_id, _norm(ticker), float(quantity), float(avg_cost), now_iso()),
        )


def delete_position(
    ticker: str, user_id: str = DEFAULT_USER_ID, conn: sqlite3.Connection | None = None
) -> None:
    with use_connection(conn) as c:
        c.execute("DELETE FROM positions WHERE user_id = ? AND ticker = ?", (user_id, _norm(ticker)))


# --- trades ----------------------------------------------------------------------------------------


def insert_trade(
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    user_id: str = DEFAULT_USER_ID,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Append a trade; returns {id, ticker, side, quantity, price, executed_at}."""
    side = side.strip().lower()
    if side not in ("buy", "sell"):
        raise ValueError(f"Invalid trade side: {side!r}")
    trade = {
        "id": new_id(),
        "ticker": _norm(ticker),
        "side": side,
        "quantity": float(quantity),
        "price": float(price),
        "executed_at": now_iso(),
    }
    with use_connection(conn) as c:
        c.execute(
            "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (trade["id"], user_id, trade["ticker"], side, trade["quantity"], trade["price"],
             trade["executed_at"]),
        )
    return trade


def get_trades(user_id: str = DEFAULT_USER_ID, limit: int = 100) -> list[dict]:
    """Most recent trades first."""
    with use_connection(None) as c:
        rows = c.execute(
            "SELECT id, ticker, side, quantity, price, executed_at FROM trades WHERE user_id = ? "
            "ORDER BY executed_at DESC, rowid DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# --- portfolio_snapshots ---------------------------------------------------------------------------


def insert_snapshot(
    total_value: float, user_id: str = DEFAULT_USER_ID, conn: sqlite3.Connection | None = None
) -> dict:
    """Record a portfolio value; returns {id, total_value, recorded_at}."""
    snap = {"id": new_id(), "total_value": float(total_value), "recorded_at": now_iso()}
    with use_connection(conn) as c:
        c.execute(
            "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) VALUES (?, ?, ?, ?)",
            (snap["id"], user_id, snap["total_value"], snap["recorded_at"]),
        )
    return snap


def get_snapshots(user_id: str = DEFAULT_USER_ID, limit: int | None = None) -> list[dict]:
    """Oldest first. With `limit`, the most recent `limit` snapshots (still oldest first)."""
    with use_connection(None) as c:
        rows = c.execute(
            "SELECT id, total_value, recorded_at FROM portfolio_snapshots WHERE user_id = ? "
            "ORDER BY recorded_at DESC, rowid DESC LIMIT ?",
            (user_id, -1 if limit is None else limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# --- chat_messages ---------------------------------------------------------------------------------


def insert_chat_message(
    role: str,
    content: str,
    actions: dict | list | None = None,
    user_id: str = DEFAULT_USER_ID,
) -> dict:
    """Store a message; returns {id, role, content, actions, created_at} with actions as given."""
    if role not in ("user", "assistant"):
        raise ValueError(f"Invalid chat role: {role!r}")
    msg = {"id": new_id(), "role": role, "content": content, "actions": actions, "created_at": now_iso()}
    with use_connection(None) as c:
        c.execute(
            "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (msg["id"], user_id, role, content, None if actions is None else json.dumps(actions),
             msg["created_at"]),
        )
    return msg


def get_chat_messages(user_id: str = DEFAULT_USER_ID, limit: int = 50) -> list[dict]:
    """The most recent `limit` messages, oldest first, with `actions` parsed from JSON."""
    with use_connection(None) as c:
        rows = c.execute(
            "SELECT id, role, content, actions, created_at FROM chat_messages WHERE user_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    messages = []
    for r in reversed(rows):
        msg = dict(r)
        msg["actions"] = json.loads(msg["actions"]) if msg["actions"] is not None else None
        messages.append(msg)
    return messages
