"""LLM client error handling and process_chat orchestration (no network: completion is patched)."""

import json
from types import SimpleNamespace

import pytest

import db
import llm.chat as chat
import llm.client as client
from llm import process_chat
from llm.client import LLMError, get_chat_response


def _completion_returning(content):
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    fake_completion.calls = calls
    return fake_completion


def _reply(message="ok", trades=(), watchlist_changes=()):
    return json.dumps({"message": message, "trades": list(trades), "watchlist_changes": list(watchlist_changes)})


@pytest.fixture
def live_mode(monkeypatch):
    """Real (non-mock) code path with a dummy key; tests patch client.completion."""
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")


@pytest.fixture
def mock_mode(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")


# --- client ---------------------------------------------------------------------------------------


async def test_client_uses_cerebras_structured_output(live_mode, monkeypatch):
    fake = _completion_returning(_reply("hello"))
    monkeypatch.setattr(client, "completion", fake)
    reply = await get_chat_response([{"role": "user", "content": "hi"}])
    assert reply.message == "hello"
    kwargs = fake.calls[0]
    assert kwargs["model"] == "openrouter/openai/gpt-oss-120b"
    assert kwargs["extra_body"] == {"provider": {"order": ["cerebras"]}}
    assert kwargs["reasoning_effort"] == "low"
    assert kwargs["response_format"] is chat.ChatResponse
    assert kwargs["timeout"] > 0


async def test_client_missing_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(client, "completion", lambda **_: pytest.fail("should not be called"))
    with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
        await get_chat_response([])


async def test_client_api_error(live_mode, monkeypatch):
    def boom(**_):
        raise RuntimeError("502 from provider")

    monkeypatch.setattr(client, "completion", boom)
    with pytest.raises(LLMError, match="unavailable"):
        await get_chat_response([])


async def test_client_timeout_error(live_mode, monkeypatch):
    class Timeout(Exception):
        pass

    def slow(**_):
        raise Timeout("timed out")

    monkeypatch.setattr(client, "completion", slow)
    with pytest.raises(LLMError, match="too long"):
        await get_chat_response([])


@pytest.mark.parametrize("content", [None, "", "I am not JSON", '{"trades": []}'])
async def test_client_malformed_reply(live_mode, monkeypatch, content):
    monkeypatch.setattr(client, "completion", _completion_returning(content))
    with pytest.raises(LLMError, match="rephrase"):
        await get_chat_response([])


# --- process_chat with the real services + temp db (conftest fixtures) ----------------------------


async def test_mock_buy_executes_and_persists(mock_mode, db_path, price_cache, market_source):
    result = await process_chat("Buy 5 AAPL", price_cache, market_source)
    assert result == {
        "message": "Mock: executing buy 5 AAPL.",
        "trades": [
            {"ticker": "AAPL", "side": "buy", "quantity": 5.0, "status": "executed", "price": 190.0, "error": None}
        ],
        "watchlist_changes": [],
    }
    assert db.get_position("AAPL")["quantity"] == 5.0
    assert db.get_cash_balance() == pytest.approx(10000.0 - 950.0)

    messages = db.get_chat_messages()
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "Buy 5 AAPL"),
        ("assistant", "Mock: executing buy 5 AAPL."),
    ]
    assert messages[0]["actions"] is None
    assert messages[1]["actions"] == {"trades": result["trades"], "watchlist_changes": []}


async def test_mock_failed_trade_reports_error(mock_mode, db_path, price_cache, market_source):
    result = await process_chat("sell 3 AAPL", price_cache, market_source)
    trade = result["trades"][0]
    assert trade["status"] == "failed"
    assert "AAPL" in trade["error"]
    assert trade["price"] is None
    assert result["message"].startswith("Mock: executing sell 3 AAPL.")
    assert "could not be completed" in result["message"]
    assert trade["error"] in result["message"]
    assert db.get_cash_balance() == 10000.0


async def test_mock_watchlist_add_and_remove(mock_mode, db_path, price_cache, market_source):
    added = await process_chat("add PYPL", price_cache, market_source)
    assert added["message"] == "Mock: add PYPL to watchlist."
    assert added["watchlist_changes"] == [{"ticker": "PYPL", "action": "add", "status": "executed", "error": None}]
    assert "PYPL" in [w["ticker"] for w in db.get_watchlist()]
    assert price_cache.get_price("PYPL") is not None

    duplicate = await process_chat("add PYPL", price_cache, market_source)
    assert duplicate["watchlist_changes"][0]["status"] == "failed"
    assert "already" in duplicate["watchlist_changes"][0]["error"]

    removed = await process_chat("remove pypl", price_cache, market_source)
    assert removed["message"] == "Mock: remove PYPL from watchlist."
    assert removed["watchlist_changes"][0]["status"] == "executed"
    assert "PYPL" not in [w["ticker"] for w in db.get_watchlist()]


async def test_mock_default_reports_total_value(mock_mode, db_path, price_cache, market_source):
    result = await process_chat("hello there", price_cache, market_source)
    assert result == {
        "message": "Mock: I'm FinAlly, your AI trading assistant. Your portfolio is worth $10,000.00.",
        "trades": [],
        "watchlist_changes": [],
    }


async def test_live_path_executes_llm_actions(live_mode, db_path, price_cache, market_source, monkeypatch):
    fake = _completion_returning(
        _reply(
            "Adding PYPL and buying.",
            trades=[{"ticker": "PYPL", "side": "buy", "quantity": 2}, {"ticker": "MSFT", "side": "buy", "quantity": 1000}],
            watchlist_changes=[{"ticker": "PYPL", "action": "add"}],
        )
    )
    monkeypatch.setattr(client, "completion", fake)
    result = await process_chat("add paypal and buy 2, also 1000 MSFT", price_cache, market_source)

    # Watchlist change runs first so the new ticker has a price for the trade.
    assert result["watchlist_changes"][0]["status"] == "executed"
    pypl, msft = result["trades"]
    assert pypl["status"] == "executed" and pypl["price"] == price_cache.get_price("PYPL")
    assert msft["status"] == "failed" and "Insufficient cash" in msft["error"]
    assert result["message"].startswith("Adding PYPL and buying.")
    assert "Buy 1000 MSFT failed: Insufficient cash" in result["message"]

    # The prompt carried the system prompt, the portfolio context and the user message.
    sent = fake.calls[0]["messages"]
    assert "FinAlly" in sent[0]["content"]
    assert "Cash: $10,000.00" in sent[1]["content"] and "AAPL | $190.00" in sent[1]["content"]
    assert sent[-1] == {"role": "user", "content": "add paypal and buy 2, also 1000 MSFT"}


async def test_live_path_includes_history(live_mode, db_path, price_cache, market_source, monkeypatch):
    monkeypatch.setattr(client, "completion", _completion_returning(_reply("first")))
    await process_chat("first question", price_cache, market_source)
    fake = _completion_returning(_reply("second"))
    monkeypatch.setattr(client, "completion", fake)
    await process_chat("second question", price_cache, market_source)

    sent = fake.calls[0]["messages"]
    assert [(m["role"], m["content"]) for m in sent[2:]] == [
        ("user", "first question"),
        ("assistant", "first"),
        ("user", "second question"),
    ]


async def test_live_path_llm_failure_is_friendly(live_mode, db_path, price_cache, market_source, monkeypatch):
    monkeypatch.setattr(client, "completion", _completion_returning("garbage"))
    result = await process_chat("buy 5 AAPL", price_cache, market_source)
    assert result["trades"] == [] and result["watchlist_changes"] == []
    assert "rephrase" in result["message"]
    assert db.get_position("AAPL") is None
    assert [m["role"] for m in db.get_chat_messages()] == ["user", "assistant"]


async def test_missing_key_is_friendly(db_path, price_cache, market_source, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = await process_chat("hi", price_cache, market_source)
    assert "OPENROUTER_API_KEY" in result["message"]
    assert result["trades"] == [] and result["watchlist_changes"] == []


# --- process_chat with stubbed services (unexpected failures) -------------------------------------


class _StubDB:
    def __init__(self, fail_writes=False, fail_reads=False):
        self.saved = []
        self.fail_writes = fail_writes
        self.fail_reads = fail_reads

    def get_chat_messages(self, user_id="default", limit=50):
        if self.fail_reads:
            raise RuntimeError("db down")
        return []

    def insert_chat_message(self, role, content, actions=None, user_id="default"):
        if self.fail_writes:
            raise RuntimeError("db down")
        self.saved.append((role, content, actions, user_id))
        return {}


class _TradeError(Exception):
    pass


class _WatchlistError(Exception):
    pass


def _stub_services(execute_trade=None, add_ticker=None, broken_context=False):
    def summary(price_cache, user_id="default"):
        if broken_context:
            raise RuntimeError("no portfolio")
        return {"total_value": 500.0, "cash_balance": 500.0, "positions_value": 0.0, "positions": []}

    def watchlist(price_cache, user_id="default"):
        if broken_context:
            raise RuntimeError("no watchlist")
        return []

    async def default_add(ticker, price_cache, market_source, user_id="default"):
        return {"ticker": ticker}

    portfolio = SimpleNamespace(
        TradeError=_TradeError,
        get_portfolio_summary=summary,
        execute_trade=execute_trade or (lambda *a, **k: {"price": 1.0}),
    )
    watch = SimpleNamespace(
        WatchlistError=_WatchlistError,
        get_watchlist_with_prices=watchlist,
        add_ticker=add_ticker or default_add,
        remove_ticker=default_add,
    )
    return portfolio, watch


async def test_unexpected_action_errors_are_contained(mock_mode, monkeypatch):
    def explode(*args, **kwargs):
        raise KeyError("bug")

    portfolio, watch = _stub_services(execute_trade=explode)
    stub_db = _StubDB()
    monkeypatch.setattr(chat, "portfolio_service", portfolio)
    monkeypatch.setattr(chat, "watchlist_service", watch)
    monkeypatch.setattr(chat, "db", stub_db)

    result = await process_chat("buy 1 AAPL", None, None, user_id="u1")
    assert result["trades"][0]["status"] == "failed"
    assert result["trades"][0]["error"] == "Internal error while executing trade"
    assert [s[0] for s in stub_db.saved] == ["user", "assistant"]
    assert all(s[3] == "u1" for s in stub_db.saved)


async def test_watchlist_service_error_text_is_returned(mock_mode, monkeypatch):
    async def reject(ticker, price_cache, market_source, user_id="default"):
        raise _WatchlistError("Invalid ticker: 'X!'")

    portfolio, watch = _stub_services(add_ticker=reject)
    monkeypatch.setattr(chat, "portfolio_service", portfolio)
    monkeypatch.setattr(chat, "watchlist_service", watch)
    monkeypatch.setattr(chat, "db", _StubDB())

    result = await process_chat("watch XYZ", None, None)
    assert result["watchlist_changes"] == [
        {"ticker": "XYZ", "action": "add", "status": "failed", "error": "Invalid ticker: 'X!'"}
    ]
    assert "Adding XYZ to watchlist failed: Invalid ticker" in result["message"]


async def test_context_and_db_failures_do_not_raise(live_mode, monkeypatch):
    portfolio, watch = _stub_services(broken_context=True)
    monkeypatch.setattr(chat, "portfolio_service", portfolio)
    monkeypatch.setattr(chat, "watchlist_service", watch)
    monkeypatch.setattr(chat, "db", _StubDB(fail_writes=True, fail_reads=True))
    fake = _completion_returning(_reply("still here"))
    monkeypatch.setattr(client, "completion", fake)

    result = await process_chat("hi", None, None)
    assert result == {"message": "still here", "trades": [], "watchlist_changes": []}
    assert "Portfolio data is currently unavailable" in fake.calls[0]["messages"][1]["content"]


async def test_unexpected_llm_exception_is_friendly(live_mode, monkeypatch):
    portfolio, watch = _stub_services()
    monkeypatch.setattr(chat, "portfolio_service", portfolio)
    monkeypatch.setattr(chat, "watchlist_service", watch)
    monkeypatch.setattr(chat, "db", _StubDB())

    async def broken(messages):
        raise ValueError("unexpected")

    monkeypatch.setattr(chat, "get_chat_response", broken)
    result = await process_chat("hi", None, None)
    assert result["message"].startswith("Sorry, something went wrong")
    assert result["trades"] == [] and result["watchlist_changes"] == []


@pytest.mark.parametrize("value, expected", [("true", True), ("TRUE", True), ("1", True), ("false", False), ("", False)])
def test_mock_mode_flag(monkeypatch, value, expected):
    monkeypatch.setenv("LLM_MOCK", value)
    assert chat.is_mock_mode() is expected
