# ─────────────────────────────────────────────────────────────────────────────
# oneshot.py — stream ONE real (or mock) Generator turn. The M2 proof of life.
# READING ORDER: backend #19
#
# WHAT THIS FILE DOES:
#   Runs a single Generator turn through the ModelProvider and streams it to the UI
#   over the SAME events the crew will use (agent_turn_started → token_stream →
#   agent_turn_completed → cost_update). This is where the provider layer, the config,
#   the cost path, and the event pipe first meet — end to end, with real spend tracked.
#
# WHY it exists separate from the M3 orchestrator: it isolates "call a model and bill
#   it" from "run a 4-role debate with a human gate". Get the plumbing right here; the
#   orchestrator (M3) then repeats this shape four times with real role prompts.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging

from app.config import get_config
from app.cost import record_and_summarize
from app.events import event_bus
from app.providers.base import ChatMessage, StreamDone, TextDelta, Usage
from app.providers.factory import get_provider
from app.settings import get_settings

logger = logging.getLogger("aicompany.oneshot")

# A minimal Generator prompt for this smoke test. The real, JSON-producing role
# prompts (verbatim from PROMPT.md §9) arrive with the crew in M3.
GENERATOR_PROMPT = (
    "You are the Generator in a small product ideation team. Given the founder's seed "
    "idea, propose 3-5 distinct, concrete project ideas that one person could build with "
    "AI coding agents in a couple of weeks. For each: a short bold name, a 2-3 sentence "
    "pitch, and who would use it. Answer in brief markdown. Be concrete, not visionary."
)


async def run_oneshot(session_id: str, seed: str) -> None:
    """Stream a single Generator turn for `seed`, emitting the standard turn events.

    Exists as M2's DoD: in mock mode it streams canned text for free; with a real key
    it streams live tokens and the cost meter moves. Any failure becomes an `error`
    event so the server never crashes on a bad model response (§13).
    """
    settings = get_settings()
    provider = get_provider(settings)
    model = get_config().roles.get("generator", "deepseek/deepseek-chat")

    event_bus.publish("phase_changed", {"phase": "ideation"}, session_id)
    event_bus.publish("agent_turn_started", {"role": "generator", "round": 1}, session_id)

    messages = [
        ChatMessage(role="system", content=GENERATOR_PROMPT),
        ChatMessage(role="user", content=seed),
    ]

    usage = Usage()
    try:
        async for event in provider.stream_chat(model, messages):
            if isinstance(event, TextDelta):
                payload = {"role": "generator", "text": event.text}
                event_bus.publish("token_stream", payload, session_id)
            elif isinstance(event, StreamDone):
                usage = event.usage

        event_bus.publish(
            "agent_turn_completed",
            {
                "role": "generator",
                "round": 1,
                "usage": {"in": usage.tokens_in, "out": usage.tokens_out},
            },
            session_id,
        )

        # Price + persist off the event loop (SQLite calls are blocking), then report.
        cost_payload = await asyncio.to_thread(record_and_summarize, session_id, model, usage)
        event_bus.publish("cost_update", cost_payload, session_id)
        logger.info(
            "oneshot %s complete: %d in / %d out", session_id, usage.tokens_in, usage.tokens_out
        )

    except Exception as error:  # noqa: BLE001 — a bad model response must not crash us
        logger.exception("oneshot %s failed", session_id)
        event_bus.publish(
            "error",
            {"where": "oneshot", "message": str(error), "recoverable": True},
            session_id,
        )
