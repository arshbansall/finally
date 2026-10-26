from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services.watchlist import (
    WatchlistError,
    add_ticker,
    get_watchlist_with_prices,
    remove_ticker,
)

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class AddTickerRequest(BaseModel):
    ticker: str


@router.get("")
async def watchlist(request: Request) -> dict:
    return {"tickers": get_watchlist_with_prices(request.app.state.price_cache)}


@router.post("", status_code=201)
async def add(body: AddTickerRequest, request: Request) -> dict:
    state = request.app.state
    try:
        return await add_ticker(body.ticker, state.price_cache, state.market_source)
    except WatchlistError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


@router.delete("/{ticker}")
async def remove(ticker: str, request: Request) -> dict:
    state = request.app.state
    try:
        return await remove_ticker(ticker, state.price_cache, state.market_source)
    except WatchlistError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
