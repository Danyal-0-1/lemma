# ─────────────────────────────────────────────────────────────────────────────
# litellm_provider.py — real streaming model calls via LiteLLM.
# READING ORDER: backend #12
#
# WHAT THIS FILE DOES:
#   Implements ModelProvider using LiteLLM, which speaks to DeepSeek, Anthropic,
#   OpenAI, and local OpenAI-compatible servers through ONE function (acompletion).
#   It streams text out as it arrives and reports token usage at the end.
#
# WHY the retry loop:
#   Networks and model APIs fail transiently — a rate limit, a dropped connection, a
#   brief 500. We retry the CONNECTION a few times with exponential backoff before
#   giving up, so a hiccup doesn't kill a crew turn. We do NOT retry once tokens have
#   started flowing (that would duplicate text); a mid-stream failure propagates and
#   the caller turns it into an `error` event. Providers never touch the event bus —
#   staying a pure layer is what keeps them testable and swappable.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import litellm

from app.providers.base import ChatMessage, StreamDone, StreamEvent, TextDelta, Usage

logger = logging.getLogger("aicompany.providers.litellm")

# One model call may not exceed this many seconds (PROMPT.md §13).
REQUEST_TIMEOUT_SECONDS = 120
# A provider-side generation ceiling is the most reliable spend/memory bound.
MAX_OUTPUT_TOKENS = 8_192
# How many times to retry establishing the stream after a transient failure.
MAX_RETRIES = 3


def _transient_errors() -> tuple[type[Exception], ...]:
    """Return the LiteLLM exception classes we consider worth retrying.

    Exists as a small compatibility shim: we look the classes up by name so this
    keeps working even if a LiteLLM version drops or renames one. Auth/bad-request
    errors are deliberately excluded — retrying them just wastes time.
    """
    names = [
        "Timeout",
        "APIConnectionError",
        "RateLimitError",
        "ServiceUnavailableError",
        "InternalServerError",
    ]
    return tuple(getattr(litellm, name) for name in names if hasattr(litellm, name))


TRANSIENT_ERRORS = _transient_errors()


class LiteLLMProvider:
    """A ModelProvider that calls real models through LiteLLM.

    Exists as the "live" half of the provider layer. It is selected only when
    MOCK_LLM=false and a matching API key is configured.
    """

    async def _open_stream(self, model: str, payload: list[dict[str, str]]) -> AsyncIterator:
        """Start a streaming completion, retrying transient failures with backoff.

        Exists to isolate the fragile part — establishing the connection — so the
        streaming loop below can assume it has a live stream. Raises the last error
        if all retries are exhausted, or immediately for non-transient errors.
        """
        attempt = 0
        while True:
            try:
                # stream=True yields chunks; include_usage asks the provider to send
                # a final chunk carrying token counts (OpenAI-compatible behavior).
                return await litellm.acompletion(
                    model=model,
                    messages=payload,
                    stream=True,
                    stream_options={"include_usage": True},
                    max_tokens=MAX_OUTPUT_TOKENS,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except TRANSIENT_ERRORS as error:
                attempt += 1
                if attempt > MAX_RETRIES:
                    logger.error("giving up on %s after %d retries: %s", model, MAX_RETRIES, error)
                    raise
                # Exponential backoff: 1s, 2s, 4s — give the upstream time to recover.
                delay = 2 ** (attempt - 1)
                logger.warning(
                    "transient error from %s (retry %d in %ds): %s", model, attempt, delay, error
                )
                await asyncio.sleep(delay)

    async def stream_chat(
        self, model: str, messages: list[ChatMessage]
    ) -> AsyncIterator[StreamEvent]:
        """Stream a real completion: yield text chunks, then one StreamDone with usage."""
        payload = [message.model_dump() for message in messages]
        stream = await self._open_stream(model, payload)

        # We accumulate the answer so we can estimate output tokens if the provider
        # doesn't send usage (some don't). Input tokens we can count up front.
        collected_text: list[str] = []
        reported_usage: Usage | None = None

        async for chunk in stream:
            # A streamed chunk carries a delta of new text (or none, e.g. the final
            # usage-only chunk). getattr keeps us safe across slightly different shapes.
            choices = getattr(chunk, "choices", None)
            if choices:
                delta = getattr(choices[0], "delta", None)
                text = getattr(delta, "content", None) if delta else None
                if text:
                    collected_text.append(text)
                    yield TextDelta(text=text)

            usage = getattr(chunk, "usage", None)
            if usage is not None:
                reported_usage = Usage(
                    tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
                    tokens_out=getattr(usage, "completion_tokens", 0) or 0,
                )

        final_usage = reported_usage or self._estimate_usage(model, payload, collected_text)
        yield StreamDone(usage=final_usage)

    def _estimate_usage(
        self, model: str, payload: list[dict[str, str]], text_parts: list[str]
    ) -> Usage:
        """Estimate token usage when the provider didn't report it.

        Exists so the cost meter still moves for models/endpoints that omit usage in
        streaming mode. LiteLLM's token_counter gives a close-enough count; a rough
        number is far better than a silently stuck meter.
        """
        try:
            tokens_in = litellm.token_counter(model=model, messages=payload)
            answer = "".join(text_parts)
            tokens_out = litellm.token_counter(model=model, text=answer) if answer else 0
        except Exception as error:  # noqa: BLE001 — estimation must never crash a turn
            logger.warning("usage estimation failed for %s: %s", model, error)
            return Usage()
        return Usage(tokens_in=tokens_in, tokens_out=tokens_out)
