"""FinAlly FastAPI application: REST API, SSE stream and the static frontend."""

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

# Real environment variables win over .env values.
load_dotenv(PROJECT_ROOT / ".env", override=False)

from fastapi import FastAPI  # noqa: E402

import db  # noqa: E402
from app.routes import chat, health, portfolio, watchlist  # noqa: E402
from app.services.portfolio import record_snapshot  # noqa: E402
from app.services.tickers import desired_tickers, sync_tracked_tickers  # noqa: E402
from app.static import create_static_router  # noqa: E402
from market import PriceCache, create_market_data_source, stream_router  # noqa: E402

logger = logging.getLogger(__name__)

SNAPSHOT_INTERVAL_SECONDS = 30.0


async def snapshot_loop(app: FastAPI, interval: float = SNAPSHOT_INTERVAL_SECONDS) -> None:
    """Record a portfolio snapshot every `interval` seconds; also re-sync tracked tickers."""
    while True:
        await asyncio.sleep(interval)
        try:
            await sync_tracked_tickers(app.state.price_cache, app.state.market_source)
            record_snapshot(app.state.price_cache)
        except Exception:
            logger.exception("Portfolio snapshot failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    price_cache = PriceCache()
    market_source = create_market_data_source(price_cache)
    app.state.price_cache = price_cache
    app.state.market_source = market_source

    await market_source.start(sorted(desired_tickers()))
    record_snapshot(price_cache)
    snapshot_task = asyncio.create_task(snapshot_loop(app))
    try:
        yield
    finally:
        snapshot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await snapshot_task
        await market_source.stop()


def static_dir() -> Path:
    return Path(os.environ.get("FINALLY_STATIC_DIR") or BACKEND_DIR / "static")


def create_app() -> FastAPI:
    # API docs live under /api so every non-API path belongs to the frontend.
    app = FastAPI(
        title="FinAlly",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.include_router(health.router)
    app.include_router(portfolio.router)
    app.include_router(watchlist.router)
    app.include_router(chat.router)
    app.include_router(stream_router)

    # The static catch-all must come last so it never shadows an API route.
    directory = static_dir()
    if directory.is_dir():
        app.include_router(create_static_router(directory))
    return app


app = create_app()
