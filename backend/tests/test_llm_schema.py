"""Structured-output schema, lenient parsing, prompts and mock-mode patterns."""

import json

import pytest

from llm.mock import mock_chat_response
from llm.prompts import SYSTEM_PROMPT, build_messages, build_portfolio_context
from llm.schema import ChatResponse, ParseError, parse_chat_response


# --- schema ---------------------------------------------------------------------------------------


def test_schema_is_strict_mode_friendly():
    from litellm.utils import type_to_response_format_param

    param = type_to_response_format_param(ChatResponse)
    schema = param["json_schema"]["schema"]
    assert param["json_schema"]["strict"] is True
    assert set(schema["required"]) == {"message", "trades", "watchlist_changes"}
    assert schema["additionalProperties"] is False
    for name in ("TradeInstruction", "WatchlistInstruction"):
        sub = schema["$defs"][name]
        assert sub["additionalProperties"] is False
        assert set(sub["required"]) == set(sub["properties"])


def test_schema_validates_full_response():
    reply = ChatResponse.model_validate_json(
        json.dumps(
            {
                "message": "Buying",
                "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10}],
                "watchlist_changes": [{"ticker": "PYPL", "action": "add"}],
            }
        )
    )
    assert reply.trades[0].quantity == 10.0
    assert reply.watchlist_changes[0].action == "add"


# --- lenient parsing ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload, n_trades, n_changes",
    [
        ({"message": "hi", "trades": [], "watchlist_changes": []}, 0, 0),
        ({"message": "hi"}, 0, 0),
        ({"message": "hi", "trades": None, "watchlist_changes": None}, 0, 0),
        ({"message": "hi", "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 1}]}, 1, 0),
        ({"message": "hi", "watchlist_changes": [{"ticker": "PYPL", "action": "remove"}]}, 0, 1),
        (
            {
                "message": "hi",
                "trades": [
                    {"ticker": "AAPL", "side": "buy", "quantity": 1},
                    {"ticker": "MSFT", "side": "sell", "quantity": 2.5},
                ],
                "watchlist_changes": [{"ticker": "PYPL", "action": "add"}, {"ticker": "NFLX", "action": "remove"}],
            },
            2,
            2,
        ),
    ],
)
def test_parse_valid_shapes(payload, n_trades, n_changes):
    reply = parse_chat_response(json.dumps(payload))
    assert reply.message == "hi"
    assert len(reply.trades) == n_trades
    assert len(reply.watchlist_changes) == n_changes


def test_parse_normalizes_case_and_aliases():
    reply = parse_chat_response(
        json.dumps(
            {
                "message": "ok",
                "trades": [{"ticker": " aapl ", "side": "BUY", "quantity": "3"}],
                "watchlist_changes": [{"ticker": "pypl", "action": "Watch"}, {"ticker": "v", "action": "unwatch"}],
            }
        )
    )
    assert reply.trades[0].model_dump() == {"ticker": "AAPL", "side": "buy", "quantity": 3.0}
    assert [(c.ticker, c.action) for c in reply.watchlist_changes] == [("PYPL", "add"), ("V", "remove")]


def test_parse_strips_code_fences_and_prose():
    body = '{"message": "fenced", "trades": [], "watchlist_changes": []}'
    assert parse_chat_response(f"```json\n{body}\n```").message == "fenced"
    assert parse_chat_response(f"Sure! Here you go: {body} Hope that helps.").message == "fenced"


def test_parse_drops_malformed_action_items():
    reply = parse_chat_response(
        json.dumps(
            {
                "message": "partial",
                "trades": [
                    {"ticker": "AAPL", "side": "hold", "quantity": 1},
                    {"ticker": "AAPL", "side": "buy"},
                    {"ticker": "AAPL", "side": "buy", "quantity": "lots"},
                    "buy AAPL",
                    {"ticker": "MSFT", "side": "sell", "quantity": 1},
                ],
                "watchlist_changes": [{"ticker": "PYPL", "action": "star"}, {"action": "add"}, 42],
            }
        )
    )
    assert [t.ticker for t in reply.trades] == ["MSFT"]
    # A missing ticker becomes "" and is rejected later by the service layer, not here.
    assert [(c.ticker, c.action) for c in reply.watchlist_changes] == [("", "add")]


def test_parse_ignores_non_list_actions():
    reply = parse_chat_response(json.dumps({"message": "x", "trades": "none", "watchlist_changes": {"a": 1}}))
    assert reply.trades == [] and reply.watchlist_changes == []


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "not json at all",
        "{broken json",
        "[1, 2, 3]",
        json.dumps({"trades": []}),
        json.dumps({"message": ""}),
        json.dumps({"message": 42}),
    ],
)
def test_parse_rejects_unusable_replies(text):
    with pytest.raises(ParseError):
        parse_chat_response(text)


# --- mock mode ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, side, qty, ticker, message",
    [
        ("Buy 5 AAPL", "buy", 5.0, "AAPL", "Mock: executing buy 5 AAPL."),
        ("please SELL 2 msft now", "sell", 2.0, "MSFT", "Mock: executing sell 2 MSFT."),
        ("buy 0.5 nvda", "buy", 0.5, "NVDA", "Mock: executing buy 0.5 NVDA."),
        ("buy 10 BRK.B", "buy", 10.0, "BRK.B", "Mock: executing buy 10 BRK.B."),
    ],
)
def test_mock_trades(text, side, qty, ticker, message):
    reply = mock_chat_response(text, 10000.0)
    assert reply.message == message
    assert [t.model_dump() for t in reply.trades] == [{"ticker": ticker, "side": side, "quantity": qty}]
    assert reply.watchlist_changes == []


@pytest.mark.parametrize(
    "text, action, ticker, message",
    [
        ("add PYPL", "add", "PYPL", "Mock: add PYPL to watchlist."),
        ("Please Add pypl", "add", "PYPL", "Mock: add PYPL to watchlist."),
        ("remove NFLX", "remove", "NFLX", "Mock: remove NFLX from watchlist."),
        ("watch amd", "add", "AMD", "Mock: add AMD to watchlist."),
        ("UNWATCH tsla", "remove", "TSLA", "Mock: remove TSLA from watchlist."),
    ],
)
def test_mock_watchlist(text, action, ticker, message):
    reply = mock_chat_response(text, 10000.0)
    assert reply.message == message
    assert [c.model_dump() for c in reply.watchlist_changes] == [{"ticker": ticker, "action": action}]
    assert reply.trades == []


@pytest.mark.parametrize("text", ["hello", "How is my portfolio doing?", "buy some apple", ""])
def test_mock_default(text):
    reply = mock_chat_response(text, 12345.678)
    assert reply.message == "Mock: I'm FinAlly, your AI trading assistant. Your portfolio is worth $12,345.68."
    assert reply.trades == [] and reply.watchlist_changes == []


def test_mock_default_without_portfolio():
    assert mock_chat_response("hi", None).message.endswith("worth $n/a.")


# --- prompts --------------------------------------------------------------------------------------


PORTFOLIO = {
    "cash_balance": 8100.0,
    "positions_value": 1905.0,
    "total_value": 10005.0,
    "unrealized_pnl": 5.0,
    "unrealized_pnl_pct": 0.26,
    "positions": [
        {
            "ticker": "AAPL",
            "quantity": 10,
            "avg_cost": 190.0,
            "current_price": 190.5,
            "market_value": 1905.0,
            "unrealized_pnl": 5.0,
            "unrealized_pnl_pct": 0.26,
            "weight": 100.0,
        }
    ],
}
WATCHLIST = [
    {"ticker": "AAPL", "price": 190.5, "previous_price": 190.4, "change_pct": 0.26, "direction": "up"},
    {"ticker": "PYPL", "price": None, "previous_price": None, "change_pct": None, "direction": None},
]


def test_system_prompt_identity():
    assert "FinAlly, an AI trading assistant" in SYSTEM_PROMPT
    assert "JSON" in SYSTEM_PROMPT


def test_portfolio_context_contents():
    context = build_portfolio_context(PORTFOLIO, WATCHLIST)
    assert "Total value: $10,005.00" in context
    assert "Cash: $8,100.00" in context
    assert "AAPL | 10 | $190.00 | $190.50 | $1,905.00 | $5.00 (+0.26%) | 100.0%" in context
    assert "PYPL | n/a | n/a" in context


def test_portfolio_context_handles_empty_and_missing_data():
    empty = dict(PORTFOLIO, positions=[], positions_value=0.0)
    assert "No open positions" in build_portfolio_context(empty, [])
    assert "Watchlist is empty" in build_portfolio_context(empty, [])
    context = build_portfolio_context(None, None)
    assert "Portfolio data is currently unavailable" in context
    assert "Watchlist data is currently unavailable" in context


def test_build_messages_order_and_history_actions():
    history = [
        {"role": "user", "content": "buy 5 AAPL", "actions": None},
        {
            "role": "assistant",
            "content": "Buying 5 AAPL.",
            "actions": {
                "trades": [
                    {"ticker": "AAPL", "side": "buy", "quantity": 5, "status": "executed", "price": 190.0, "error": None}
                ],
                "watchlist_changes": [{"ticker": "PYPL", "action": "add", "status": "failed", "error": "dup"}],
            },
        },
        {"role": "system", "content": "ignored"},
    ]
    messages = build_messages("CTX", history, "and now?")
    assert [m["role"] for m in messages] == ["system", "system", "user", "assistant", "user"]
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert messages[1]["content"] == "CTX"
    assert "buy 5 AAPL executed at $190.00" in messages[3]["content"]
    assert "watchlist add PYPL FAILED (dup)" in messages[3]["content"]
    assert messages[-1] == {"role": "user", "content": "and now?"}
