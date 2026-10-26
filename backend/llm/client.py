"""LiteLLM -> OpenRouter (Cerebras provider) client for structured chat replies."""

import asyncio
import logging
import os

# Use litellm's bundled model-cost map instead of fetching it over the network at import time.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm  # noqa: E402
from litellm import completion  # noqa: E402

from llm.schema import ChatResponse, ParseError, parse_chat_response  # noqa: E402

litellm.suppress_debug_info = True

logger = logging.getLogger(__name__)

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}
REQUEST_TIMEOUT_SECONDS = 30.0


class LLMError(Exception):
    """The LLM could not produce a usable reply. The message is user-facing."""


def _call_sync(messages: list[dict]) -> str | None:
    response = completion(
        model=MODEL,
        messages=messages,
        response_format=ChatResponse,
        reasoning_effort="low",
        extra_body=EXTRA_BODY,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return response.choices[0].message.content


async def get_chat_response(messages: list[dict]) -> ChatResponse:
    """Call the LLM off the event loop and parse its structured reply.

    Raises ``LLMError`` (with a friendly message) on a missing key, API/network failure,
    timeout or an unparseable reply.
    """
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise LLMError(
            "The AI assistant isn't configured yet: set OPENROUTER_API_KEY in the .env file "
            "(or LLM_MOCK=true for mock replies)."
        )
    try:
        content = await asyncio.wait_for(
            asyncio.to_thread(_call_sync, messages), timeout=REQUEST_TIMEOUT_SECONDS + 5
        )
    except TimeoutError:
        logger.warning("LLM request timed out")
        raise LLMError("The AI assistant took too long to respond. Please try again.") from None
    except Exception as exc:  # litellm raises many provider-specific exception types
        logger.exception("LLM request failed")
        if "timeout" in type(exc).__name__.lower():
            raise LLMError("The AI assistant took too long to respond. Please try again.") from None
        raise LLMError("The AI assistant is unavailable right now. Please try again shortly.") from None

    try:
        return parse_chat_response(content)
    except ParseError as exc:
        logger.warning("Could not parse LLM reply (%s): %r", exc, (content or "")[:500])
        raise LLMError("Sorry, I couldn't process that request. Could you rephrase it?") from None
