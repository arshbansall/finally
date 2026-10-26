"""Chat orchestration: context -> LLM (or mock) -> auto-execute actions -> persist -> response."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

import db
from app.services import portfolio as portfolio_service
from app.services import watchlist as watchlist_service
from llm.client import LLMError, get_chat_response
from llm.mock import mock_chat_response
from llm.prompts import build_messages, build_portfolio_context
from llm.schema import ChatResponse

logger = logging.getLogger(__name__)

# Project-root .env (backend/../.env); real environment variables win.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

HISTORY_LIMIT = 20


def is_mock_mode() -> bool:
    return os.environ.get("LLM_MOCK", "").strip().lower() in ("1", "true", "yes")


def _load_context(price_cache, user_id: str) -> tuple[dict | None, list[dict] | None]:
    portfolio = watchlist = None
    try:
        portfolio = portfolio_service.get_portfolio_summary(price_cache, user_id=user_id)
    except Exception:
        logger.exception("Failed to load portfolio summary for chat context")
    try:
        watchlist = watchlist_service.get_watchlist_with_prices(price_cache, user_id=user_id)
    except Exception:
        logger.exception("Failed to load watchlist for chat context")
    return portfolio, watchlist


def _load_history(user_id: str) -> list[dict]:
    try:
        return db.get_chat_messages(user_id=user_id, limit=HISTORY_LIMIT)
    except Exception:
        logger.exception("Failed to load chat history")
        return []


def _save_message(role: str, content: str, actions: dict | None, user_id: str) -> None:
    try:
        db.insert_chat_message(role, content, actions=actions, user_id=user_id)
    except Exception:
        logger.exception("Failed to persist %s chat message", role)


def _execute_trades(reply: ChatResponse, price_cache, user_id: str) -> list[dict]:
    results = []
    for trade in reply.trades:
        result = {
            "ticker": trade.ticker,
            "side": trade.side,
            "quantity": trade.quantity,
            "status": "failed",
            "price": None,
            "error": None,
        }
        try:
            executed = portfolio_service.execute_trade(
                trade.ticker, trade.side, trade.quantity, price_cache, user_id=user_id
            )
            result.update(status="executed", price=executed.get("price"))
        except portfolio_service.TradeError as exc:
            result["error"] = str(exc)
        except Exception:
            logger.exception("Unexpected error executing chat trade %s", trade)
            result["error"] = "Internal error while executing trade"
        results.append(result)
    return results


async def _execute_watchlist_changes(reply: ChatResponse, price_cache, market_source, user_id: str) -> list[dict]:
    results = []
    for change in reply.watchlist_changes:
        result = {"ticker": change.ticker, "action": change.action, "status": "failed", "error": None}
        fn = watchlist_service.add_ticker if change.action == "add" else watchlist_service.remove_ticker
        try:
            await fn(change.ticker, price_cache, market_source, user_id=user_id)
            result["status"] = "executed"
        except watchlist_service.WatchlistError as exc:
            result["error"] = str(exc)
        except Exception:
            logger.exception("Unexpected error applying chat watchlist change %s", change)
            result["error"] = "Internal error while updating watchlist"
        results.append(result)
    return results


def _failure_note(trades: list[dict], changes: list[dict]) -> str:
    lines = []
    for t in trades:
        if t["status"] == "failed":
            lines.append(f"- {t['side'].capitalize()} {t['quantity']:g} {t['ticker']} failed: {t['error']}")
    for c in changes:
        if c["status"] == "failed":
            verb = "Adding" if c["action"] == "add" else "Removing"
            lines.append(f"- {verb} {c['ticker']} {'to' if c['action'] == 'add' else 'from'} watchlist failed: {c['error']}")
    if not lines:
        return ""
    return "\n\nNote: some actions could not be completed:\n" + "\n".join(lines)


async def process_chat(message: str, price_cache, market_source, user_id: str = "default") -> dict:
    """Handle one chat turn and return the POST /api/chat response shape (CONTRACT §4).

    Never raises for LLM, network or parse failures: those become a friendly message with no actions.
    """
    portfolio, watchlist = _load_context(price_cache, user_id)
    history = _load_history(user_id)
    _save_message("user", message, None, user_id)

    if is_mock_mode():
        total_value = portfolio.get("total_value") if portfolio else None
        reply = mock_chat_response(message, total_value)
    else:
        messages = build_messages(build_portfolio_context(portfolio, watchlist), history, message)
        try:
            reply = await get_chat_response(messages)
        except LLMError as exc:
            reply = ChatResponse(message=str(exc), trades=[], watchlist_changes=[])
        except Exception:
            logger.exception("Unexpected error getting LLM reply")
            reply = ChatResponse(
                message="Sorry, something went wrong on my end. Please try again.",
                trades=[],
                watchlist_changes=[],
            )

    # Watchlist changes first so a trade in a newly added ticker has a price available.
    watchlist_results = await _execute_watchlist_changes(reply, price_cache, market_source, user_id)
    trade_results = _execute_trades(reply, price_cache, user_id)

    final_message = reply.message + _failure_note(trade_results, watchlist_results)
    actions = {"trades": trade_results, "watchlist_changes": watchlist_results}
    _save_message("assistant", final_message, actions, user_id)

    return {"message": final_message, "trades": trade_results, "watchlist_changes": watchlist_results}
