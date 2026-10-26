"""SSE endpoint streaming the price cache to the browser."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import threading
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

logger = logging.getLogger(__name__)

STREAM_INTERVAL = 0.5  # seconds between cache checks
HEARTBEAT_INTERVAL = 15.0  # keep idle connections alive (e.g. between Massive polls)
RETRY_MS = 1000

stream_router = APIRouter()

# Set when the server receives SIGINT/SIGTERM. Uvicorn's graceful shutdown waits for
# open responses to finish *before* running lifespan shutdown (and by default waits
# forever), so an endless SSE stream would block exit until the browser goes away.
# Streams poll this flag and end themselves instead.
shutdown_event = threading.Event()
SHUTDOWN_SIGNALS = (signal.SIGINT, signal.SIGTERM)


def install_shutdown_signal_hook() -> None:
    """Wrap the server's SIGINT/SIGTERM handlers so they also set ``shutdown_event``.

    Must run after the server installed its handlers (we call it per stream request).
    Only callable handlers are wrapped, so the default "exit on signal" behaviour is
    untouched when no server is managing signals. Idempotent; main thread only.
    """
    if threading.current_thread() is not threading.main_thread():
        return
    for sig in SHUTDOWN_SIGNALS:
        current = signal.getsignal(sig)
        if not callable(current) or getattr(current, "_finally_sse_hook", False):
            continue

        def hook(signum, frame, _previous=current):
            shutdown_event.set()
            _previous(signum, frame)

        hook._finally_sse_hook = True  # type: ignore[attr-defined]
        signal.signal(sig, hook)


def format_prices_event(cache: PriceCache) -> str:
    payload = {ticker: update.to_dict() for ticker, update in cache.get_all().items()}
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def price_event_stream(
    request: Request,
    cache: PriceCache,
    interval: float = STREAM_INTERVAL,
    heartbeat_interval: float = HEARTBEAT_INTERVAL,
) -> AsyncIterator[str]:
    """Yield an event with every ticker whenever the cache changes, until the client
    leaves or the server starts shutting down."""
    yield f"retry: {RETRY_MS}\n\n"
    last_version = -1
    idle = 0.0
    while not shutdown_event.is_set() and not await request.is_disconnected():
        if cache.version != last_version:
            last_version = cache.version
            idle = 0.0
            yield format_prices_event(cache)
        elif idle >= heartbeat_interval:
            idle = 0.0
            yield ": ping\n\n"
        await asyncio.sleep(interval)
        idle += interval


@stream_router.get("/api/stream/prices")
async def stream_prices(request: Request) -> StreamingResponse:
    cache: PriceCache = request.app.state.price_cache
    install_shutdown_signal_hook()
    return StreamingResponse(
        price_event_stream(request, cache, STREAM_INTERVAL, HEARTBEAT_INTERVAL),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
