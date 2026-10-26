"""Deterministic mock LLM for LLM_MOCK=true (E2E tests, development without an API key).

Patterns (case-insensitive) are pinned in planning/CONTRACT.md §3.4 — the E2E tests depend on
these exact strings, so coordinate with integration-tester before changing them.
"""

import re

from llm.schema import ChatResponse, TradeInstruction, WatchlistInstruction

_TICKER = r"([A-Za-z][A-Za-z0-9.]{0,9})"
_TRADE_RE = re.compile(rf"\b(buy|sell)\s+(\d+(?:\.\d+)?)\s+{_TICKER}\b", re.IGNORECASE)
_WATCHLIST_RE = re.compile(rf"\b(add|remove|watch|unwatch)\s+{_TICKER}\b", re.IGNORECASE)
_WATCHLIST_ACTIONS = {"add": "add", "watch": "add", "remove": "remove", "unwatch": "remove"}


def _format_qty(qty: float) -> str:
    return f"{qty:g}"


def mock_chat_response(user_message: str, total_value: float | None) -> ChatResponse:
    trade = _TRADE_RE.search(user_message)
    if trade:
        side = trade.group(1).lower()
        quantity = float(trade.group(2))
        ticker = trade.group(3).upper()
        return ChatResponse(
            message=f"Mock: executing {side} {_format_qty(quantity)} {ticker}.",
            trades=[TradeInstruction(ticker=ticker, side=side, quantity=quantity)],
            watchlist_changes=[],
        )

    change = _WATCHLIST_RE.search(user_message)
    if change:
        action = _WATCHLIST_ACTIONS[change.group(1).lower()]
        ticker = change.group(2).upper()
        preposition = "to" if action == "add" else "from"
        return ChatResponse(
            message=f"Mock: {action} {ticker} {preposition} watchlist.",
            trades=[],
            watchlist_changes=[WatchlistInstruction(ticker=ticker, action=action)],
        )

    value = "n/a" if total_value is None else f"{total_value:,.2f}"
    return ChatResponse(
        message=f"Mock: I'm FinAlly, your AI trading assistant. Your portfolio is worth ${value}.",
        trades=[],
        watchlist_changes=[],
    )
