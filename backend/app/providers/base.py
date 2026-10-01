# ─────────────────────────────────────────────────────────────────────────────
# base.py — the ModelProvider interface and the types that cross it.
# READING ORDER: backend #11  (teaches: Protocol interfaces + tagged unions)
#
# WHAT THIS FILE DOES:
#   Defines the ONE shape a "chat model" has in this app: given a model name and a
#   list of messages, stream back text and, at the end, token usage. Two concrete
#   providers implement it — MockProvider (free canned text) and LiteLLMProvider
#   (real calls). The rest of the app depends only on THIS interface, never on which
#   provider is active. That's what lets mock mode be a true drop-in.
#
# WHY a streamed union instead of "return a string":
#   The UI shows tokens as they arrive, and we need usage for the cost meter. So the
#   provider yields a sequence of events: many TextDelta (chunks of text), then one
#   StreamDone (the final usage). The consumer accumulates text and reads usage at
#   the end — a small, explicit protocol that's easy to reason about.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol

from pydantic import BaseModel


class ChatMessage(BaseModel):
    """One message in a chat: a role and its text content.

    Exists as the neutral message shape we hand to any provider, so callers never
    build provider-specific dicts. `role` is constrained to the three chat roles.
    """

    role: Literal["system", "user", "assistant"]
    content: str


class Usage(BaseModel):
    """Token counts for one completion, used to price the cost meter."""

    tokens_in: int = 0
    tokens_out: int = 0


class TextDelta(BaseModel):
    """A chunk of streamed text (part of the model's answer as it's generated)."""

    text: str


class StreamDone(BaseModel):
    """The final event of a stream, carrying the completion's token usage.

    Exists so the consumer has a clear "the answer is finished, here's the cost"
    signal — rather than guessing when a stream of text has ended.
    """

    usage: Usage


# A provider yields a sequence of these: zero-or-more TextDelta, then one StreamDone.
# This "tagged union" lets the consumer tell text from the end-of-stream marker by
# type, with the type checker enforcing that both cases are handled.
StreamEvent = TextDelta | StreamDone


class ModelProvider(Protocol):
    """The interface every chat-model backend implements.

    Exists so the crew, the mentor, and the oneshot endpoint all talk to "a model"
    the same way, whether it's the mock or a real API. A Protocol (structural typing)
    means a class is a ModelProvider simply by having a matching stream_chat — no
    inheritance required.
    """

    def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        *,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a chat completion for `messages` using `model`.

        Yields TextDelta chunks as text is produced, then exactly one StreamDone with
        the token usage. Declared as a normal method returning AsyncIterator because
        an `async def ... yield` implementation IS an async iterator when called.
        """
        ...
