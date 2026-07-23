# ─────────────────────────────────────────────────────────────────────────────
# explain.py — the mentor: explain a diff, a file, a selection, or answer a question.
# READING ORDER: backend #45
#
# WHAT THIS FILE DOES: builds a prompt for the MENTOR role from whatever the user gave
# us (some content to explain, a question, and/or the active tab as context), then
# streams the answer over the SAME turn events the crew uses — as role "mentor". So the
# explanation appears right in the Conversation, no separate panel (PROMPT.md §11).
#
# WHY it reuses the provider + event pipe: the mentor is just another model call. By
# emitting agent_turn_started / token_stream / agent_turn_completed with role "mentor",
# the existing Conversation renders it for free (with the mentor's green color).
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging

from app.config import get_config
from app.cost import record_and_summarize
from app.events import event_bus
from app.ideation.roles import ROLE_PROMPTS
from app.providers.base import ChatMessage, StreamDone, TextDelta, Usage
from app.providers.factory import get_provider
from app.settings import get_settings

logger = logging.getLogger("aicompany.explain")


def _build_user_message(
    content: str | None, question: str | None, context: str | None, context_label: str | None
) -> str:
    """Assemble the user message for the mentor from the available pieces."""
    parts: list[str] = []
    if context:
        label = context_label or "context"
        parts.append(f"Here is the current {label} for reference:\n{context}")
    if content:
        parts.append(f"Explain this specifically:\n{content}")
    if question:
        parts.append(f"The founder asks: {question}")
    if not parts:
        parts.append("Explain what you see and offer one thing to try.")
    return "\n\n".join(parts)


async def run_explain(
    session_id: str,
    content: str | None,
    question: str | None,
    context: str | None,
    context_label: str | None,
) -> None:
    """Stream a mentor explanation into the Conversation (role "mentor").

    Exists as the body of POST /api/explain. In mock mode it streams a canned lesson;
    with a real key it explains the actual content. Failures become an `error` event.
    """
    settings = get_settings()
    provider = get_provider(settings)
    model = get_config().roles.get("explain", "deepseek/deepseek-chat")

    event_bus.publish("agent_turn_started", {"role": "mentor", "round": 0}, session_id)
    user_message = _build_user_message(content, question, context, context_label)
    messages = [
        ChatMessage(role="system", content=ROLE_PROMPTS["mentor"]),
        ChatMessage(role="user", content=user_message),
    ]

    usage = Usage()
    try:
        async for event in provider.stream_chat(model, messages):
            if isinstance(event, TextDelta):
                payload = {"role": "mentor", "text": event.text}
                event_bus.publish("token_stream", payload, session_id)
            elif isinstance(event, StreamDone):
                usage = event.usage

        event_bus.publish(
            "agent_turn_completed",
            {
                "role": "mentor",
                "round": 0,
                "usage": {"in": usage.tokens_in, "out": usage.tokens_out},
            },
            session_id,
        )
        cost_payload = await asyncio.to_thread(record_and_summarize, session_id, model, usage)
        event_bus.publish("cost_update", cost_payload, session_id)

    except Exception as error:  # noqa: BLE001 — a bad model response must not crash us
        logger.exception("explain %s failed", session_id)
        event_bus.publish(
            "error",
            {"where": "explain", "message": str(error), "recoverable": True},
            session_id,
        )
