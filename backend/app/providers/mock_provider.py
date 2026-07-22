# ─────────────────────────────────────────────────────────────────────────────
# mock_provider.py — zero-cost canned streams (MOCK_LLM=true, the default).
# READING ORDER: backend #13
#
# WHAT THIS FILE DOES:
#   Implements the SAME ModelProvider interface as the real one, but instead of
#   calling an API it streams believable canned text with small delays, then reports
#   a rough token usage. This makes the entire app runnable and developable with no
#   API keys and no cost — mock mode is a real feature, not a stub (PROMPT.md §13).
#
# WHY role detection: the crew's roles each get a different system prompt. The mock
#   peeks at that prompt to pick a fitting canned answer, so a mock run "feels" like
#   a real debate. M2 only needs the Generator; more roles get schema-valid canned
#   JSON in M3, and this dispatch is where that will slot in.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.providers.base import ChatMessage, StreamDone, StreamEvent, TextDelta, Usage

# Delay between streamed chunks, so mock output visibly "types" like a live model.
CHUNK_DELAY_SECONDS = 0.03

# Canned answers keyed by a lowercase keyword we look for in the system prompt.
# Kept short and markdown-friendly; the Conversation renders them.
_CANNED_BY_ROLE: dict[str, str] = {
    "generator": (
        "Here are three concrete directions for your seed:\n\n"
        "1. **HabitDeck** — a tiny daily checklist that turns streaks into a visible score.\n"
        "2. **NudgeBot** — sends one well-timed reminder a day based on your calendar gaps.\n"
        "3. **WhyLog** — a 20-second end-of-day journal that surfaces patterns weekly.\n\n"
        "All three are buildable solo in a couple of weeks."
    ),
}

# Used when no role keyword matches — still a believable, harmless completion.
_DEFAULT_CANNED = (
    "This is a mock response. Set `MOCK_LLM=false` and add a provider key in "
    "`backend/.env` to stream real model output here."
)


def _pick_canned(messages: list[ChatMessage]) -> str:
    """Choose a canned answer by looking for a role keyword in the system prompt.

    Exists so the mock's output matches whoever is "speaking". Falls back to a
    generic message so an unrecognized prompt still streams something sensible.
    """
    system_text = " ".join(m.content for m in messages if m.role == "system").lower()
    for keyword, answer in _CANNED_BY_ROLE.items():
        if keyword in system_text:
            return answer
    return _DEFAULT_CANNED


def _chunk_words(text: str, words_per_chunk: int = 3) -> list[str]:
    """Split text into small word-groups so it streams like a live model."""
    words = text.split(" ")
    chunks: list[str] = []
    for start in range(0, len(words), words_per_chunk):
        chunks.append(" ".join(words[start : start + words_per_chunk]) + " ")
    return chunks


def _estimate_tokens(text: str) -> int:
    """Rough token count (~1.3 tokens per word) — good enough for the mock meter."""
    return int(len(text.split()) * 1.3)


class MockProvider:
    """A ModelProvider that streams canned text at zero cost.

    Exists as the default provider so the app is fully demoable offline. It mirrors
    the real provider's contract exactly: many TextDelta, then one StreamDone.
    """

    async def stream_chat(
        self, model: str, messages: list[ChatMessage]
    ) -> AsyncIterator[StreamEvent]:
        """Stream a canned answer, then report a plausible (fake) token usage."""
        answer = _pick_canned(messages)

        for chunk in _chunk_words(answer):
            yield TextDelta(text=chunk)
            await asyncio.sleep(CHUNK_DELAY_SECONDS)

        prompt_text = " ".join(m.content for m in messages)
        usage = Usage(tokens_in=_estimate_tokens(prompt_text), tokens_out=_estimate_tokens(answer))
        yield StreamDone(usage=usage)
