"""Structured-output schema for the chat LLM, plus lenient parsing of its replies."""

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)


class TradeInstruction(BaseModel):
    """A market order the assistant wants to place."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    side: Literal["buy", "sell"]
    quantity: float


class WatchlistInstruction(BaseModel):
    """A watchlist modification the assistant wants to make."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    action: Literal["add", "remove"]


class ChatResponse(BaseModel):
    """The JSON object the LLM must return (PLAN §9).

    Every field is required and extra keys are forbidden so the schema is valid in
    OpenAI-style strict structured-output mode; the model returns empty lists when
    there is nothing to do.
    """

    model_config = ConfigDict(extra="forbid")

    message: str
    trades: list[TradeInstruction]
    watchlist_changes: list[WatchlistInstruction]


class ParseError(ValueError):
    """The LLM reply could not be interpreted as a ChatResponse."""


_SIDE_ALIASES = {"buy": "buy", "sell": "sell"}
_ACTION_ALIASES = {"add": "add", "watch": "add", "remove": "remove", "unwatch": "remove", "delete": "remove"}
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


def _extract_json_object(text: str) -> dict:
    text = text.strip()
    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the outermost {...} span, e.g. when the model wraps JSON in prose.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ParseError("no JSON object found in LLM reply") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ParseError(f"invalid JSON in LLM reply: {exc}") from None
    if not isinstance(data, dict):
        raise ParseError("LLM reply JSON is not an object")
    return data


def _normalize_trade(item: object) -> TradeInstruction | None:
    if not isinstance(item, dict):
        return None
    try:
        side = _SIDE_ALIASES.get(str(item.get("side", "")).strip().lower())
        return TradeInstruction(
            ticker=str(item.get("ticker", "")).strip().upper(),
            side=side,
            quantity=float(item.get("quantity")),
        )
    except (TypeError, ValueError, ValidationError):
        return None


def _normalize_watchlist_change(item: object) -> WatchlistInstruction | None:
    if not isinstance(item, dict):
        return None
    try:
        action = _ACTION_ALIASES.get(str(item.get("action", "")).strip().lower())
        return WatchlistInstruction(ticker=str(item.get("ticker", "")).strip().upper(), action=action)
    except (TypeError, ValueError, ValidationError):
        return None


def parse_chat_response(text: str | None) -> ChatResponse:
    """Parse an LLM reply leniently.

    Accepts code fences, surrounding prose, missing/null action lists, upper-case sides and
    ``watch``/``unwatch`` aliases. Individual malformed action items are dropped (and logged).
    Raises ``ParseError`` only if there is no usable ``message``.
    """
    if not text or not text.strip():
        raise ParseError("empty LLM reply")
    data = _extract_json_object(text)

    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ParseError("LLM reply has no 'message' string")

    raw_trades = data.get("trades") or []
    raw_changes = data.get("watchlist_changes") or []
    if not isinstance(raw_trades, list):
        raw_trades = []
    if not isinstance(raw_changes, list):
        raw_changes = []

    trades = [t for t in map(_normalize_trade, raw_trades) if t is not None]
    changes = [c for c in map(_normalize_watchlist_change, raw_changes) if c is not None]
    dropped = (len(raw_trades) - len(trades)) + (len(raw_changes) - len(changes))
    if dropped:
        logger.warning("Dropped %d malformed action(s) from LLM reply", dropped)

    return ChatResponse(message=message.strip(), trades=trades, watchlist_changes=changes)
