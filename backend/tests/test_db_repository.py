import sqlite3
import threading
import uuid
from datetime import datetime

import pytest

import db
from db import connection


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(connection, "_db_path", connection._db_path)
    path = tmp_path / "finally.db"
    db.init_db(path)
    return path


def _is_uuid(value: str) -> bool:
    return str(uuid.UUID(value)) == value


def _is_utc_iso(value: str) -> bool:
    return datetime.fromisoformat(value).utcoffset().total_seconds() == 0


# --- users_profile ---------------------------------------------------------------------------------


def test_cash_balance_get_set():
    assert db.get_cash_balance() == 10000.0
    db.set_cash_balance(8100.25)
    assert db.get_cash_balance() == 8100.25
    assert isinstance(db.get_cash_balance(), float)


def test_cash_balance_unknown_user_and_upsert():
    assert db.get_cash_balance(user_id="alice") == 0.0
    db.set_cash_balance(500, user_id="alice")
    assert db.get_cash_balance(user_id="alice") == 500.0
    assert db.get_cash_balance() == 10000.0


# --- watchlist -------------------------------------------------------------------------------------


def test_watchlist_rows_shape():
    rows = db.get_watchlist()
    assert len(rows) == 10
    for row in rows:
        assert set(row) == {"id", "ticker", "added_at"}
        assert _is_uuid(row["id"])
        assert _is_utc_iso(row["added_at"])


def test_watchlist_add_remove():
    assert db.add_watchlist_ticker("PYPL") is True
    assert db.add_watchlist_ticker("PYPL") is False
    assert db.add_watchlist_ticker("pypl") is False  # normalized to uppercase
    assert db.get_watchlist()[-1]["ticker"] == "PYPL"
    assert db.remove_watchlist_ticker("pypl") is True
    assert db.remove_watchlist_ticker("PYPL") is False
    assert "PYPL" not in [w["ticker"] for w in db.get_watchlist()]


def test_watchlist_ordered_by_insertion():
    for t in ("ZZZ", "AAA", "MMM"):
        db.add_watchlist_ticker(t)
    assert [w["ticker"] for w in db.get_watchlist()][-3:] == ["ZZZ", "AAA", "MMM"]


def test_watchlist_unique_constraint_enforced(fresh_db):
    conn = db.get_connection()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, 'default', 'AAPL', 'x')",
                (str(uuid.uuid4()),),
            )
    finally:
        conn.close()


def test_watchlist_is_per_user():
    assert db.get_watchlist(user_id="bob") == []
    assert db.add_watchlist_ticker("AAPL", user_id="bob") is True
    assert [w["ticker"] for w in db.get_watchlist(user_id="bob")] == ["AAPL"]
    assert db.remove_watchlist_ticker("AAPL", user_id="bob") is True
    assert "AAPL" in [w["ticker"] for w in db.get_watchlist()]


# --- positions -------------------------------------------------------------------------------------


def test_positions_empty_initially():
    assert db.get_positions() == []
    assert db.get_position("AAPL") is None


def test_upsert_insert_and_update_keeps_id():
    db.upsert_position("aapl", 10, 190.0)
    pos = db.get_position("AAPL")
    assert set(pos) == {"id", "ticker", "quantity", "avg_cost", "updated_at"}
    assert pos["ticker"] == "AAPL" and pos["quantity"] == 10.0 and pos["avg_cost"] == 190.0
    assert _is_uuid(pos["id"]) and _is_utc_iso(pos["updated_at"])

    db.upsert_position("AAPL", 15.5, 192.0)
    updated = db.get_position("AAPL")
    assert updated["id"] == pos["id"]
    assert updated["quantity"] == 15.5 and updated["avg_cost"] == 192.0
    assert updated["updated_at"] >= pos["updated_at"]
    assert len(db.get_positions()) == 1


def test_positions_ordered_by_ticker_and_delete():
    for t in ("TSLA", "AAPL", "MSFT"):
        db.upsert_position(t, 1, 100.0)
    assert [p["ticker"] for p in db.get_positions()] == ["AAPL", "MSFT", "TSLA"]
    db.delete_position("msft")
    assert [p["ticker"] for p in db.get_positions()] == ["AAPL", "TSLA"]
    db.delete_position("NOPE")  # no-op
    assert len(db.get_positions()) == 2


def test_fractional_quantities():
    db.upsert_position("NVDA", 0.125, 800.0)
    assert db.get_position("NVDA")["quantity"] == 0.125


def test_positions_are_per_user():
    db.upsert_position("AAPL", 1, 100.0, user_id="bob")
    assert db.get_positions() == []
    assert db.get_position("AAPL", user_id="bob")["quantity"] == 1.0


# --- trades ----------------------------------------------------------------------------------------


def test_insert_trade_returns_shape():
    trade = db.insert_trade("aapl", "BUY", 5, 190.12)
    assert set(trade) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
    assert trade["ticker"] == "AAPL" and trade["side"] == "buy"
    assert trade["quantity"] == 5.0 and trade["price"] == 190.12
    assert _is_uuid(trade["id"]) and _is_utc_iso(trade["executed_at"])
    assert db.get_trades() == [trade]


def test_insert_trade_rejects_bad_side():
    with pytest.raises(ValueError):
        db.insert_trade("AAPL", "short", 1, 100.0)
    assert db.get_trades() == []


def test_trades_side_check_constraint():
    conn = db.get_connection()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO trades (id, ticker, side, quantity, price, executed_at) "
                "VALUES ('x', 'AAPL', 'hold', 1, 1, 'x')"
            )
    finally:
        conn.close()


def test_get_trades_newest_first_with_limit():
    trades = [db.insert_trade("AAPL", "buy", i + 1, 100.0) for i in range(5)]
    got = db.get_trades()
    assert [t["id"] for t in got] == [t["id"] for t in reversed(trades)]
    assert [t["id"] for t in db.get_trades(limit=2)] == [trades[4]["id"], trades[3]["id"]]
    assert db.get_trades(user_id="bob") == []


# --- portfolio_snapshots ---------------------------------------------------------------------------


def test_snapshots_oldest_first():
    snaps = [db.insert_snapshot(10000.0 + i) for i in range(5)]
    assert set(snaps[0]) == {"id", "total_value", "recorded_at"}
    assert _is_uuid(snaps[0]["id"]) and _is_utc_iso(snaps[0]["recorded_at"])
    assert db.get_snapshots() == snaps


def test_snapshots_limit_returns_latest_oldest_first():
    snaps = [db.insert_snapshot(float(i)) for i in range(5)]
    assert [s["total_value"] for s in db.get_snapshots(limit=3)] == [2.0, 3.0, 4.0]
    assert db.get_snapshots(limit=0) == []
    assert len(db.get_snapshots(limit=100)) == len(snaps)


def test_snapshots_per_user():
    db.insert_snapshot(1.0, user_id="bob")
    assert db.get_snapshots() == []
    assert len(db.get_snapshots(user_id="bob")) == 1


# --- chat_messages ---------------------------------------------------------------------------------


def test_chat_message_round_trip_actions():
    actions = {
        "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 5, "status": "executed", "price": 190.12,
                    "error": None}],
        "watchlist_changes": [{"ticker": "PYPL", "action": "add", "status": "failed", "error": "nope"}],
    }
    user = db.insert_chat_message("user", "Buy 5 AAPL")
    bot = db.insert_chat_message("assistant", "Done.", actions)
    assert set(bot) == {"id", "role", "content", "actions", "created_at"}
    assert _is_uuid(bot["id"]) and _is_utc_iso(bot["created_at"])
    msgs = db.get_chat_messages()
    assert msgs == [user, bot]
    assert msgs[0]["actions"] is None
    assert msgs[1]["actions"] == actions


def test_chat_actions_list_and_empty_values():
    db.insert_chat_message("assistant", "a", [{"x": 1}])
    db.insert_chat_message("assistant", "b", [])
    db.insert_chat_message("assistant", "c", {})
    assert [m["actions"] for m in db.get_chat_messages()] == [[{"x": 1}], [], {}]


def test_chat_rejects_bad_role():
    with pytest.raises(ValueError):
        db.insert_chat_message("system", "hi")


def test_chat_limit_returns_latest_oldest_first():
    for i in range(10):
        db.insert_chat_message("user" if i % 2 == 0 else "assistant", f"m{i}")
    assert [m["content"] for m in db.get_chat_messages(limit=3)] == ["m7", "m8", "m9"]
    assert len(db.get_chat_messages()) == 10
    assert db.get_chat_messages(user_id="bob") == []


def test_chat_preserves_unicode_content():
    db.insert_chat_message("assistant", "Gain: +5% 📈 — ok")
    assert db.get_chat_messages()[0]["content"] == "Gain: +5% 📈 — ok"


# --- transactions ----------------------------------------------------------------------------------


def test_transaction_commits_grouped_writes():
    with db.transaction() as conn:
        db.set_cash_balance(8100.0, conn=conn)
        db.upsert_position("AAPL", 10, 190.0, conn=conn)
        db.insert_trade("AAPL", "buy", 10, 190.0, conn=conn)
        db.insert_snapshot(10000.0, conn=conn)
        # Reads on the same connection see uncommitted writes.
        assert db.get_cash_balance(conn=conn) == 8100.0
        assert db.get_position("AAPL", conn=conn)["quantity"] == 10.0
        assert len(db.get_positions(conn=conn)) == 1
    assert db.get_cash_balance() == 8100.0
    assert db.get_position("AAPL")["quantity"] == 10.0
    assert len(db.get_trades()) == 1
    assert len(db.get_snapshots()) == 1


def test_transaction_rolls_back_on_exception():
    db.upsert_position("MSFT", 3, 400.0)
    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            db.set_cash_balance(1.0, conn=conn)
            db.upsert_position("AAPL", 10, 190.0, conn=conn)
            db.delete_position("MSFT", conn=conn)
            db.insert_trade("AAPL", "buy", 10, 190.0, conn=conn)
            db.insert_snapshot(1.0, conn=conn)
            raise RuntimeError("boom")
    assert db.get_cash_balance() == 10000.0
    assert db.get_position("AAPL") is None
    assert db.get_position("MSFT")["quantity"] == 3.0
    assert db.get_trades() == []
    assert db.get_snapshots() == []


def test_transaction_rolls_back_on_sql_error():
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            db.set_cash_balance(1.0, conn=conn)
            conn.execute("INSERT INTO trades (id, ticker, side, quantity, price, executed_at) "
                         "VALUES ('x', 'AAPL', 'bad', 1, 1, 'x')")
    assert db.get_cash_balance() == 10000.0


def test_uncommitted_writes_invisible_to_other_connections():
    with db.transaction() as conn:
        db.set_cash_balance(5.0, conn=conn)
        assert db.get_cash_balance() == 10000.0  # separate connection, WAL snapshot
    assert db.get_cash_balance() == 5.0


def test_concurrent_transactions_from_threads_are_serialized():
    errors = []

    def worker():
        try:
            for _ in range(20):
                with db.transaction() as conn:
                    bal = db.get_cash_balance(conn=conn)
                    db.set_cash_balance(bal - 1, conn=conn)
                    db.insert_trade("AAPL", "buy", 1, 1.0, conn=conn)
        except Exception as exc:  # pragma: no cover - surfaced by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert db.get_cash_balance() == 10000.0 - 100
    assert len(db.get_trades(limit=1000)) == 100


def test_connection_usable_across_threads():
    conn = db.get_connection()
    result = []
    try:
        t = threading.Thread(target=lambda: result.append(db.get_cash_balance(conn=conn)))
        t.start()
        t.join()
    finally:
        conn.close()
    assert result == [10000.0]
