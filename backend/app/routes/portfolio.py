from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import db
from app.services.portfolio import TradeError, execute_trade, get_portfolio_summary
from app.services.tickers import sync_tracked_tickers

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class TradeRequest(BaseModel):
    ticker: str
    quantity: float
    side: str


@router.get("")
async def portfolio(request: Request) -> dict:
    return get_portfolio_summary(request.app.state.price_cache)


@router.post("/trade")
async def trade(body: TradeRequest, request: Request) -> dict:
    state = request.app.state
    try:
        result = execute_trade(body.ticker, body.side, body.quantity, state.price_cache)
    except TradeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    # A full sell of a ticker that isn't watched should stop streaming it.
    await sync_tracked_tickers(state.price_cache, state.market_source)
    return {"trade": result, "portfolio": get_portfolio_summary(state.price_cache)}


@router.get("/history")
async def history() -> dict:
    return {
        "snapshots": [
            {"total_value": s["total_value"], "recorded_at": s["recorded_at"]}
            for s in db.get_snapshots()
        ]
    }
