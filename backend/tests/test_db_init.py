import sqlite3

import pytest

import db
from db import connection

TABLES = {"users_profile", "watchlist", "positions", "trades", "portfolio_snapshots", "chat_messages"}


@pytest.fixture(autouse=True)
def _restore_db_path(monkeypatch):
    # init_db() switches the module-wide database; undo that after each test.
    monkeypatch.setattr(connection, "_db_path", connection._db_path)


def _tables(path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()


def test_init_creates_parent_dir_file_and_tables(tmp_path):
    path = tmp_path / "nested" / "dir" / "finally.db"
    db.init_db(path)
    assert path.exists()
    assert TABLES <= _tables(path)
    assert db.get_db_path() == path.resolve()


def test_seeds_default_user_and_watchlist(tmp_path):
    db.init_db(tmp_path / "f.db")
    assert db.get_cash_balance() == 10000.0
    assert [w["ticker"] for w in db.get_watchlist()] == db.DEFAULT_WATCHLIST
    assert db.DEFAULT_WATCHLIST == ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def test_init_is_idempotent_and_preserves_data(tmp_path):
    path = tmp_path / "f.db"
    db.init_db(path)
    db.set_cash_balance(1234.5)
    db.add_watchlist_ticker("PYPL")
    db.insert_trade("AAPL", "buy", 1, 190.0)
    db.init_db(path)
    db.init_db(path)
    assert db.get_cash_balance() == 1234.5
    tickers = [w["ticker"] for w in db.get_watchlist()]
    assert tickers == db.DEFAULT_WATCHLIST + ["PYPL"]
    assert len(db.get_trades()) == 1
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM users_profile").fetchone()[0] == 1
    conn.close()


def test_emptied_watchlist_is_not_reseeded(tmp_path):
    path = tmp_path / "f.db"
    db.init_db(path)
    for t in db.DEFAULT_WATCHLIST:
        assert db.remove_watchlist_ticker(t)
    db.init_db(path)
    assert db.get_watchlist() == []


def test_init_creates_missing_tables_in_existing_file(tmp_path):
    path = tmp_path / "f.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE unrelated (x INTEGER)")
    conn.commit()
    conn.close()
    db.init_db(path)
    assert TABLES | {"unrelated"} <= _tables(path)
    assert db.get_cash_balance() == 10000.0


def test_wal_mode_enabled(tmp_path):
    db.init_db(tmp_path / "f.db")
    conn = db.get_connection()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_env_var_path_and_lazy_init(tmp_path, monkeypatch):
    path = tmp_path / "env" / "lazy.db"
    monkeypatch.setenv("FINALLY_DB_PATH", str(path))
    monkeypatch.setattr(connection, "_db_path", None)
    assert not path.exists()
    # No explicit init_db(): the first repository call initializes the database.
    assert db.get_cash_balance() == 10000.0
    assert path.exists()
    assert db.get_db_path() == path.resolve()


def test_init_db_none_uses_env_var(tmp_path, monkeypatch):
    path = tmp_path / "from_env.db"
    monkeypatch.setenv("FINALLY_DB_PATH", str(path))
    db.init_db()
    assert db.get_db_path() == path.resolve()
    assert path.exists()


def test_default_path_is_project_root_db(monkeypatch):
    monkeypatch.delenv("FINALLY_DB_PATH", raising=False)
    monkeypatch.setattr(connection, "_db_path", None)
    expected = connection.Path(connection.__file__).resolve().parents[2] / "db" / "finally.db"
    assert db.get_db_path() == expected


def test_reinitializes_if_file_deleted(tmp_path):
    path = tmp_path / "f.db"
    db.init_db(path)
    db.set_cash_balance(1.0)
    for suffix in ("", "-wal", "-shm"):
        p = path.with_name(path.name + suffix)
        if p.exists():
            p.unlink()
    assert db.get_cash_balance() == 10000.0


def test_get_connection_settings(tmp_path):
    db.init_db(tmp_path / "f.db")
    conn = db.get_connection()
    try:
        assert conn.row_factory is sqlite3.Row
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()
