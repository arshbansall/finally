"""SQLite connection management and lazy initialization.

Each repository call opens a short-lived connection (cheap for SQLite) unless the caller passes one in,
which keeps things thread-safe under FastAPI's threadpool without a global lock. WAL mode lets readers
proceed while a write transaction is open.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_USER_ID = "default"
DEFAULT_CASH_BALANCE = 10000.0
DEFAULT_WATCHLIST = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "db" / "finally.db"

_init_lock = threading.Lock()
_db_path: Path | None = None  # set by init_db(); otherwise resolved from env on first use
_initialized: set[Path] = set()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def _resolve_path(db_path: str | os.PathLike | None) -> Path:
    if db_path is None:
        db_path = os.environ.get("FINALLY_DB_PATH") or _DEFAULT_DB_PATH
    return Path(db_path).expanduser().resolve()


def get_db_path() -> Path:
    """The database file currently in use."""
    return _db_path if _db_path is not None else _resolve_path(None)


def _connect(path: Path) -> sqlite3.Connection:
    # isolation_level=None: autocommit per statement; transaction() issues BEGIN/COMMIT explicitly.
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db(db_path: str | os.PathLike | None = None) -> None:
    """Create the db file/dir and missing tables, seed defaults on a fresh database. Idempotent.

    `db_path` (or, if None, FINALLY_DB_PATH / the default path) becomes the database used by all
    subsequent repository calls.
    """
    global _db_path
    path = _resolve_path(db_path)
    with _init_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect(path)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA_PATH.read_text())
            _seed(conn)
        finally:
            conn.close()
        _db_path = path
        _initialized.add(path)


def _seed(conn: sqlite3.Connection) -> None:
    # The watchlist is seeded only together with a brand-new user profile, so a user who deliberately
    # empties their watchlist doesn't get the defaults back on restart.
    conn.execute("BEGIN IMMEDIATE")
    try:
        created = conn.execute(
            "INSERT OR IGNORE INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
            (DEFAULT_USER_ID, DEFAULT_CASH_BALANCE, now_iso()),
        ).rowcount
        if created:
            added_at = now_iso()
            conn.executemany(
                "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
                [(new_id(), DEFAULT_USER_ID, t, added_at) for t in DEFAULT_WATCHLIST],
            )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def get_connection() -> sqlite3.Connection:
    """Open a new connection to the current database (lazily initializing it). Caller must close it."""
    path = get_db_path()
    if path not in _initialized or not path.exists():
        init_db(path)
    return _connect(path)


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Yield a connection inside BEGIN IMMEDIATE ... COMMIT; rolls back on any exception.

    Pass the yielded connection as `conn=` to repository functions to group writes atomically.
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    finally:
        conn.close()


@contextmanager
def use_connection(conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    """Use the caller's connection if given, otherwise a short-lived one closed on exit."""
    if conn is not None:
        yield conn
        return
    own = get_connection()
    try:
        yield own
    finally:
        own.close()
