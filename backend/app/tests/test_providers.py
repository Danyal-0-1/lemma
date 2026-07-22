# ─────────────────────────────────────────────────────────────────────────────
# test_providers.py — prove the MockProvider honors the ModelProvider contract.
# READING ORDER: backend #20
#
# The contract (base.py) is: yield zero-or-more TextDelta, then exactly one
# StreamDone carrying usage. If the mock keeps that contract, the rest of the app —
# which only knows the interface — works identically whether mock or live.
# ─────────────────────────────────────────────────────────────────────────────

from app.providers.base import ChatMessage, StreamDone, TextDelta
from app.providers.mock_provider import MockProvider


async def _collect(model: str, messages: list[ChatMessage]):
    """Drain a provider stream into (joined_text, final_usage) for easy assertions."""
    provider = MockProvider()
    text_parts: list[str] = []
    usage = None
    async for event in provider.stream_chat(model, messages):
        if isinstance(event, TextDelta):
            text_parts.append(event.text)
        elif isinstance(event, StreamDone):
            usage = event.usage
    return "".join(text_parts), usage


async def test_mock_streams_text_then_usage() -> None:
    """A mock run yields text chunks and ends with a StreamDone that has token counts."""
    messages = [
        ChatMessage(role="system", content="You are the Generator ..."),
        ChatMessage(role="user", content="a habit tracker"),
    ]

    text, usage = await _collect("deepseek/deepseek-chat", messages)

    # The Generator canned answer mentions its three ideas; check one anchor word.
    assert "HabitDeck" in text
    assert usage is not None
    # Usage must be populated (non-zero) so the cost meter has something to price.
    assert usage.tokens_out > 0
    assert usage.tokens_in > 0


async def test_mock_role_detection_falls_back() -> None:
    """With no known role keyword, the mock still streams the generic canned answer."""
    messages = [ChatMessage(role="user", content="hello there")]

    text, usage = await _collect("deepseek/deepseek-chat", messages)

    assert "mock response" in text.lower()
    assert usage is not None
