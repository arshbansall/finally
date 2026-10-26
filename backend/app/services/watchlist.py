"""Watchlist management, kept in sync with the market data source."""

import db

from app.services.tickers import DEFAULT_USER_ID, normalize_ticker


class WatchlistError(Exception):
    """A watchlist change failed; the message is user-facing.

    `status_code` maps the failure to HTTP: 400 invalid, 404 not found, 409 duplicate.
    """

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _item(ticker: str, price_cache) -> dict:
    update = price_cache.get(ticker)
    if update is None:
        return {"ticker": ticker, "price": None, "previous_price": None, "change_pct": None, "direction": None}
    return {
        "ticker": ticker,
        "price": update.price,
        "previous_price": update.previous_price,
        "change_pct": update.change_pct,
        "direction": update.direction,
    }


def get_watchlist_with_prices(price_cache, user_id: str = DEFAULT_USER_ID) -> list[dict]:
    """Watchlist tickers (oldest first) with their latest cached prices."""
    return [_item(row["ticker"], price_cache) for row in db.get_watchlist(user_id)]


async def add_ticker(ticker: str, price_cache, market_source, user_id: str = DEFAULT_USER_ID) -> dict:
    """Add a ticker to the watchlist and start streaming it. Raises WatchlistError."""
    symbol = normalize_ticker(ticker)
    if symbol is None:
        raise WatchlistError(f"Invalid ticker: {ticker!r}", 400)
    if not db.add_watchlist_ticker(symbol, user_id):
        raise WatchlistError(f"{symbol} is already in your watchlist", 409)
    if symbol not in market_source.get_tickers():
        await market_source.add_ticker(symbol)
    return _item(symbol, price_cache)


async def remove_ticker(ticker: str, price_cache, market_source, user_id: str = DEFAULT_USER_ID) -> dict:
    """Remove a ticker from the watchlist; stop streaming it unless it's still held."""
    symbol = normalize_ticker(ticker)
    if symbol is None:
        raise WatchlistError(f"Invalid ticker: {ticker!r}", 400)
    if not db.remove_watchlist_ticker(symbol, user_id):
        raise WatchlistError(f"{symbol} is not in your watchlist", 404)
    if db.get_position(symbol, user_id) is None:
        await market_source.remove_ticker(symbol)
        price_cache.remove(symbol)
    return {"ticker": symbol}
