from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

import db
import llm
from app.services.tickers import sync_tracked_tickers

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@router.post("")
async def chat(body: ChatRequest, request: Request) -> dict:
    state = request.app.state
    result = await llm.process_chat(body.message, state.price_cache, state.market_source)
    # LLM trades may have closed a position on an unwatched ticker.
    await sync_tracked_tickers(state.price_cache, state.market_source)
    return result


@router.get("")
async def history() -> dict:
    return {
        "messages": [
            {
                "id": m["id"],
                "role": m["role"],
                "content": m["content"],
                "actions": m["actions"],
                "created_at": m["created_at"],
            }
            for m in db.get_chat_messages()
        ]
    }
