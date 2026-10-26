import pytest

import db
import llm


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_startup_wires_state_and_records_snapshot(app, client):
    assert app.state.market_source.started
    assert set(app.state.market_source.get_tickers()) == {
        "AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX",
    }
    snapshots = client.get("/api/portfolio/history").json()["snapshots"]
    assert snapshots == [{"total_value": 10000.0, "recorded_at": snapshots[0]["recorded_at"]}]


def test_shutdown_stops_market_source(app):
    from fastapi.testclient import TestClient

    with TestClient(app):
        pass
    assert app.state.market_source.stopped


def test_startup_tracks_held_unwatched_tickers(app, db_path):
    db.upsert_position("PYPL", 3, 60.0)
    from fastapi.testclient import TestClient

    with TestClient(app):
        assert "PYPL" in app.state.market_source.get_tickers()


# --- portfolio -----------------------------------------------------------------------------------


def test_get_portfolio_fresh(client):
    response = client.get("/api/portfolio")
    assert response.status_code == 200
    assert response.json() == {
        "cash_balance": 10000.0,
        "positions_value": 0.0,
        "total_value": 10000.0,
        "unrealized_pnl": 0.0,
        "unrealized_pnl_pct": 0.0,
        "positions": [],
    }


def test_buy_trade(client):
    response = client.post("/api/portfolio/trade", json={"ticker": "aapl", "quantity": 10, "side": "buy"})
    assert response.status_code == 200
    body = response.json()
    assert set(body["trade"]) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
    assert body["trade"]["ticker"] == "AAPL"
    assert body["trade"]["price"] == 190.0
    portfolio = body["portfolio"]
    assert portfolio["cash_balance"] == 8100.0
    assert portfolio["total_value"] == 10000.0
    position = portfolio["positions"][0]
    assert set(position) == {
        "ticker", "quantity", "avg_cost", "current_price", "market_value",
        "unrealized_pnl", "unrealized_pnl_pct", "weight",
    }
    assert position["weight"] == 100.0
    assert client.get("/api/portfolio").json() == portfolio


def test_sell_trade_and_history(client):
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 10, "side": "buy"})
    response = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 10, "side": "sell"})
    assert response.status_code == 200
    assert response.json()["portfolio"]["positions"] == []
    assert response.json()["portfolio"]["cash_balance"] == 10000.0

    snapshots = client.get("/api/portfolio/history").json()["snapshots"]
    assert len(snapshots) == 3  # startup + two trades
    assert all(set(s) == {"total_value", "recorded_at"} for s in snapshots)
    assert [s["recorded_at"] for s in snapshots] == sorted(s["recorded_at"] for s in snapshots)


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"ticker": "AAPL", "quantity": 1000, "side": "buy"}, "Insufficient cash"),
        ({"ticker": "AAPL", "quantity": 1, "side": "sell"}, "don't own any AAPL"),
        ({"ticker": "AAPL", "quantity": 0, "side": "buy"}, "greater than zero"),
        ({"ticker": "AAPL", "quantity": 1, "side": "hold"}, "Invalid side"),
        ({"ticker": "$$$", "quantity": 1, "side": "buy"}, "Invalid ticker"),
        ({"ticker": "PYPL", "quantity": 1, "side": "buy"}, "No price available"),
    ],
)
def test_trade_validation_errors(client, body, detail):
    response = client.post("/api/portfolio/trade", json=body)
    assert response.status_code == 400
    assert detail in response.json()["detail"]


def test_trade_malformed_body_is_422(client):
    assert client.post("/api/portfolio/trade", json={"ticker": "AAPL"}).status_code == 422
    assert client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": "x", "side": "buy"}).status_code == 422


def test_full_sell_of_unwatched_ticker_stops_streaming(app, client):
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 2, "side": "buy"})
    client.delete("/api/watchlist/AAPL")
    assert "AAPL" in app.state.market_source.get_tickers()
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 2, "side": "sell"})
    assert "AAPL" not in app.state.market_source.get_tickers()


# --- watchlist -----------------------------------------------------------------------------------


def test_get_watchlist(client):
    response = client.get("/api/watchlist")
    assert response.status_code == 200
    tickers = response.json()["tickers"]
    assert len(tickers) == 10
    assert tickers[0] == {
        "ticker": "AAPL", "price": 190.0, "previous_price": 190.0, "change_pct": 0.0, "direction": "flat",
    }


def test_add_and_remove_watchlist_ticker(app, client):
    response = client.post("/api/watchlist", json={"ticker": "pypl"})
    assert response.status_code == 201
    assert response.json()["ticker"] == "PYPL"
    assert response.json()["price"] == 50.0
    assert "PYPL" in app.state.market_source.get_tickers()
    assert client.get("/api/watchlist").json()["tickers"][-1]["ticker"] == "PYPL"

    response = client.delete("/api/watchlist/pypl")
    assert response.status_code == 200
    assert response.json() == {"ticker": "PYPL"}
    assert "PYPL" not in app.state.market_source.get_tickers()
    assert "PYPL" not in [t["ticker"] for t in client.get("/api/watchlist").json()["tickers"]]


def test_add_duplicate_is_409(client):
    response = client.post("/api/watchlist", json={"ticker": "AAPL"})
    assert response.status_code == 409
    assert "already" in response.json()["detail"]


def test_add_invalid_is_400(client):
    response = client.post("/api/watchlist", json={"ticker": "bad ticker!"})
    assert response.status_code == 400
    assert "Invalid ticker" in response.json()["detail"]


def test_add_missing_body_is_422(client):
    assert client.post("/api/watchlist", json={}).status_code == 422


def test_remove_missing_is_404(client):
    response = client.delete("/api/watchlist/PYPL")
    assert response.status_code == 404
    assert "not in your watchlist" in response.json()["detail"]


# --- chat ----------------------------------------------------------------------------------------


def test_chat_delegates_to_llm(client, monkeypatch, app):
    calls = []

    async def fake_process_chat(message, price_cache, market_source, user_id="default"):
        calls.append((message, price_cache, market_source))
        return {"message": "hi", "trades": [], "watchlist_changes": []}

    monkeypatch.setattr(llm, "process_chat", fake_process_chat, raising=False)
    response = client.post("/api/chat", json={"message": "hello"})
    assert response.status_code == 200
    assert response.json() == {"message": "hi", "trades": [], "watchlist_changes": []}
    assert calls == [("hello", app.state.price_cache, app.state.market_source)]


def test_chat_invalid_body_is_422(client):
    assert client.post("/api/chat", json={}).status_code == 422
    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_chat_history(client):
    db.insert_chat_message("user", "Buy 5 AAPL")
    db.insert_chat_message("assistant", "Done", actions={"trades": [{"ticker": "AAPL"}]})
    response = client.get("/api/chat")
    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert set(messages[0]) == {"id", "role", "content", "actions", "created_at"}
    assert messages[0]["actions"] is None
    assert messages[1]["actions"] == {"trades": [{"ticker": "AAPL"}]}


# --- misc ----------------------------------------------------------------------------------------


def test_unknown_api_route_is_json_404(client):
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_chat_mock_mode_end_to_end(client):
    response = client.post("/api/chat", json={"message": "buy 5 AAPL"})
    assert response.status_code == 200
    body = response.json()
    assert body["trades"] == [
        {"ticker": "AAPL", "side": "buy", "quantity": 5, "status": "executed", "price": 190.0, "error": None}
    ]
    assert client.get("/api/portfolio").json()["cash_balance"] == 10000 - 5 * 190

    response = client.post("/api/chat", json={"message": "add PYPL"})
    assert response.json()["watchlist_changes"][0]["status"] == "executed"
    assert client.get("/api/watchlist").json()["tickers"][-1]["ticker"] == "PYPL"

    messages = client.get("/api/chat").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[1]["actions"]["trades"][0]["status"] == "executed"
