"""Ticker normalization and tracked-ticker bookkeeping."""

import re

import db

DEFAULT_USER_ID = "default"

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")


def normalize_ticker(ticker: object) -> str | None:
    """Uppercase and strip a ticker; return None if it isn't a valid symbol."""
    if not isinstance(ticker, str):
        return None
    symbol = ticker.strip().upper()
    return symbol if TICKER_RE.match(symbol) else None


def desired_tickers(user_id: str = DEFAULT_USER_ID) -> set[str]:
    """Tickers that should be streaming: watchlist ∪ open positions."""
    watched = {row["ticker"] for row in db.get_watchlist(user_id)}
    held = {row["ticker"] for row in db.get_positions(user_id)}
    return watched | held


async def sync_tracked_tickers(price_cache, market_source, user_id: str = DEFAULT_USER_ID) -> None:
    """Make the market source track exactly watchlist ∪ positions.

    Safe to call any time (e.g. after a trade sells a position to zero).
    """
    desired = desired_tickers(user_id)
    current = set(market_source.get_tickers())
    for ticker in sorted(desired - current):
        await market_source.add_ticker(ticker)
    for ticker in sorted(current - desired):
        await market_source.remove_ticker(ticker)
        price_cache.remove(ticker)
