"""Choose the market data source from the environment."""

from __future__ import annotations

import logging
import os

from .cache import PriceCache
from .fallback import FallbackDataSource
from .interface import MarketDataSource
from .massive import DEFAULT_POLL_INTERVAL, MassiveDataSource
from .simulator import SimulatorDataSource

logger = logging.getLogger(__name__)


def create_market_data_source(cache: PriceCache) -> MarketDataSource:
    """Massive REST poller if ``MASSIVE_API_KEY`` is set and non-empty, else the GBM simulator.

    The Massive poller is wrapped so it falls back to the simulator if the key is
    rejected or no snapshot succeeds during startup.
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not api_key:
        logger.info("Using the built-in market simulator")
        return SimulatorDataSource(cache)

    raw_interval = os.environ.get("MASSIVE_POLL_INTERVAL", "").strip()
    try:
        interval = float(raw_interval) if raw_interval else DEFAULT_POLL_INTERVAL
    except ValueError:
        logger.warning("Invalid MASSIVE_POLL_INTERVAL %r; using %.0fs", raw_interval, DEFAULT_POLL_INTERVAL)
        interval = DEFAULT_POLL_INTERVAL
    if interval <= 0:
        interval = DEFAULT_POLL_INTERVAL
    logger.info("Using Massive market data (poll every %.0fs)", interval)
    return FallbackDataSource(
        MassiveDataSource(cache, api_key, poll_interval=interval),
        fallback_factory=lambda: SimulatorDataSource(cache),
    )
