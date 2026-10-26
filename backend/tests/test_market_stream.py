"""SSE router: drive the ASGI app directly so the infinite stream can be cut off by a disconnect."""

import asyncio
import json
import signal

import pytest
from fastapi import FastAPI

import market.stream as stream
from market import PriceCache, stream_router


@pytest.fixture(autouse=True)
def isolate_shutdown_state():
    """Each test starts with no shutdown requested and gets its signal handlers back."""
    saved = {sig: signal.getsignal(sig) for sig in stream.SHUTDOWN_SIGNALS}
    stream.shutdown_event.clear()
    yield
    stream.shutdown_event.clear()
    for sig, handler in saved.items():
        signal.signal(sig, handler)


@pytest.fixture
def fast_stream(monkeypatch):
    monkeypatch.setattr(stream, "STREAM_INTERVAL", 0.01)
    monkeypatch.setattr(stream, "HEARTBEAT_INTERVAL", 0.05)


def make_app(cache: PriceCache) -> FastAPI:
    app = FastAPI()
    app.state.price_cache = cache
    app.include_router(stream_router)
    return app


async def run_stream(app: FastAPI, until, timeout: float = 3.0):
    """Request /api/stream/prices; disconnect once ``until(body_text)`` is true.

    Returns (start_message, body_text) and asserts the app finishes after the disconnect.
    """
    disconnect = asyncio.Event()
    sent: list[dict] = []
    body = ""
    request_sent = False

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        nonlocal body
        sent.append(message)
        if message["type"] == "http.response.body":
            body += message.get("body", b"").decode()
            if until(body):
                disconnect.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/stream/prices",
        "raw_path": b"/api/stream/prices",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"test"), (b"accept", b"text/event-stream")],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
    }
    # Completing at all proves the stream stops when the client disconnects.
    await asyncio.wait_for(app(scope, receive, send), timeout)
    return sent[0], body


def data_events(body: str) -> list[dict]:
    return [json.loads(chunk[len("data: "):]) for chunk in body.split("\n\n") if chunk.startswith("data: ")]


async def test_headers_retry_and_event_format(fast_stream):
    cache = PriceCache()
    cache.update("AAPL", 190.0, "2026-10-26T15:00:00.000+00:00")
    cache.update("AAPL", 190.12, "2026-10-26T15:00:00.500+00:00")
    cache.update("GOOGL", 175.0)

    start, body = await run_stream(make_app(cache), lambda b: "data: " in b)

    assert start["status"] == 200
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-cache"
    assert headers["x-accel-buffering"] == "no"

    assert body.startswith("retry: 1000\n\n")
    assert "event:" not in body  # unnamed events -> EventSource.onmessage
    event = data_events(body)[0]
    assert set(event) == {"AAPL", "GOOGL"}
    assert event["AAPL"] == {
        "ticker": "AAPL",
        "price": 190.12,
        "previous_price": 190.0,
        "open_price": 190.0,
        "timestamp": "2026-10-26T15:00:00.500+00:00",
        "direction": "up",
        "change": 0.12,
        "change_pct": 0.06,
    }


async def test_pushes_new_event_when_cache_changes(fast_stream):
    cache = PriceCache()
    cache.update("AAPL", 190.0)

    async def ticker():
        for i in range(1, 50):
            await asyncio.sleep(0.02)
            cache.update("AAPL", 190.0 + i)

    task = asyncio.create_task(ticker())
    try:
        _, body = await run_stream(make_app(cache), lambda b: b.count("data: ") >= 3)
    finally:
        task.cancel()

    prices = [e["AAPL"]["price"] for e in data_events(body)]
    assert len(prices) >= 3
    assert prices == sorted(prices) and len(set(prices)) == len(prices)


async def test_no_duplicate_events_and_heartbeat_when_idle(fast_stream):
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    _, body = await run_stream(make_app(cache), lambda b: ": ping" in b)
    assert len(data_events(body)) == 1


async def test_empty_cache_sends_empty_object(fast_stream):
    _, body = await run_stream(make_app(PriceCache()), lambda b: "data: " in b)
    assert data_events(body) == [{}]


async def test_removed_ticker_disappears_from_stream(fast_stream):
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.update("PYPL", 70.0)

    async def remove_later():
        await asyncio.sleep(0.05)
        cache.remove("PYPL")

    task = asyncio.create_task(remove_later())
    _, body = await run_stream(make_app(cache), lambda b: b.count("data: ") >= 2)
    await task
    events = data_events(body)
    assert set(events[0]) == {"AAPL", "PYPL"}
    assert set(events[-1]) == {"AAPL"}


# --- graceful server shutdown ------------------------------------------------


async def test_stream_ends_on_shutdown_without_client_disconnect(fast_stream):
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    app = make_app(cache)

    def shut_down_after_first_event(body: str) -> bool:
        if "data: " in body:
            stream.shutdown_event.set()
        return False  # never disconnect from the client side

    _, body = await run_stream(app, shut_down_after_first_event)
    assert len(data_events(body)) == 1


async def test_sigterm_ends_open_streams_and_reaches_server_handler(fast_stream):
    server_calls = []
    signal.signal(signal.SIGTERM, lambda signum, frame: server_calls.append(signum))  # stand-in for uvicorn
    cache = PriceCache()
    cache.update("AAPL", 190.0)

    def sigterm_after_first_event(body: str) -> bool:
        if "data: " in body and not server_calls:
            signal.raise_signal(signal.SIGTERM)  # the route installed the hook
        return False

    _, body = await run_stream(make_app(cache), sigterm_after_first_event)
    assert server_calls == [signal.SIGTERM]  # server still gets its signal
    assert stream.shutdown_event.is_set()
    assert len(data_events(body)) == 1


def test_signal_hook_is_idempotent():
    calls = []
    signal.signal(signal.SIGTERM, lambda signum, frame: calls.append(signum))
    stream.install_shutdown_signal_hook()
    stream.install_shutdown_signal_hook()
    signal.raise_signal(signal.SIGTERM)
    assert calls == [signal.SIGTERM]  # wrapped once, not twice
    assert stream.shutdown_event.is_set()


def test_signal_hook_leaves_default_disposition_alone():
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    stream.install_shutdown_signal_hook()
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
