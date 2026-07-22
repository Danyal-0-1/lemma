# ─────────────────────────────────────────────────────────────────────────────
# demo.py — a scripted, fake crew conversation to exercise the event pipe (M1).
# READING ORDER: backend #9
#
# WHAT THIS FILE DOES:
#   Publishes a believable ideation round — Generator → Researcher → Critic → PM —
#   WITHOUT calling any model. It streams canned text token-by-token so we can build
#   and verify the whole frontend Conversation before the real orchestrator exists.
#
# WHY it's here: M1's goal is the PIPE, not the AI. This proves events flow end to
#   end (backend publish → bus → /ws → browser render) with zero keys and zero cost.
#   The real model-driven version arrives in M2/M3; this file is disposable teaching
#   scaffolding, but it is real, working code — not a stub.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging

from app.events import event_bus

logger = logging.getLogger("aicompany.demo")

# Delay between streamed word-chunks and between turns — small enough to feel live,
# large enough to actually see the streaming happen.
CHUNK_DELAY_SECONDS = 0.05
TURN_GAP_SECONDS = 0.4

# Mock per-1M-token prices, mirroring config.toml, used to move the cost meter.
PRICE_IN_PER_MTOK = 0.28
PRICE_OUT_PER_MTOK = 0.42

# The scripted round. Each entry is one crew turn: who speaks, and what they say
# (markdown — the Conversation renders it). Token counts are invented but plausible.
DEMO_SCRIPT: list[dict[str, object]] = [
    {
        "role": "generator",
        "text": (
            "Here are three concrete takes on your seed:\n\n"
            "1. **RecipeRemix** — paste a recipe, get it rescaled and adapted to what's "
            "in your fridge.\n"
            "2. **StudyLoop** — turns lecture notes into spaced-repetition flashcards.\n"
            "3. **CommitCoach** — reviews your git diffs and suggests clearer messages.\n\n"
            "All three are buildable solo in a couple of weeks."
        ),
        "tokens_in": 320,
        "tokens_out": 96,
    },
    {
        "role": "researcher",
        "text": (
            "Quick feasibility pass:\n\n"
            "- **RecipeRemix** — lots of recipe apps exist, but fridge-aware rescaling is "
            "a real gap. Hard part: parsing messy recipe text.\n"
            "- **StudyLoop** — Anki dominates; differentiation is auto-card generation. "
            "*Weeks* of work.\n"
            "- **CommitCoach** — narrow and very feasible; a *weekend* prototype."
        ),
        "tokens_in": 410,
        "tokens_out": 104,
    },
    {
        "role": "critic",
        "text": (
            "Where these break:\n\n"
            "- RecipeRemix: who actually opens an app mid-cooking? Retention risk. "
            "**RESHAPE**.\n"
            "- StudyLoop: card *quality* is everything; bad cards kill trust. **RESHAPE**.\n"
            "- CommitCoach: small but genuinely useful and low-risk. **PURSUE** — biggest "
            "risk is it feeling like a toy."
        ),
        "tokens_in": 512,
        "tokens_out": 118,
    },
    {
        "role": "pm",
        "text": (
            "Decision: **CommitCoach**. It's the one a solo beginner can finish, verify, "
            "and actually use daily.\n\n"
            "I'll draft a Spec: read the staged diff, propose a conventional-commit "
            "message, let the user accept or edit. Non-goals: no CI, no hosting. "
            "Milestones land in the Spec tab once the real crew runs."
        ),
        "tokens_in": 640,
        "tokens_out": 132,
    },
]


def _chunk_words(text: str, words_per_chunk: int = 3) -> list[str]:
    """Split text into small word-groups so it can be streamed like a live model.

    Exists purely to simulate token streaming: we send a few words at a time with a
    delay, which is what makes the demo look like a real crew typing.
    """
    words = text.split(" ")
    chunks: list[str] = []
    for start in range(0, len(words), words_per_chunk):
        group = words[start : start + words_per_chunk]
        # Re-add the trailing space so the reassembled text reads naturally.
        chunks.append(" ".join(group) + " ")
    return chunks


def _estimate_usd(tokens_in: int, tokens_out: int) -> float:
    """Estimate cost in USD from token counts, using the mock prices above."""
    input_cost = (tokens_in / 1_000_000) * PRICE_IN_PER_MTOK
    output_cost = (tokens_out / 1_000_000) * PRICE_OUT_PER_MTOK
    return input_cost + output_cost


async def run_demo(session_id: str) -> None:
    """Stream one scripted crew round over the event bus.

    Exists as M1's end-to-end test of the pipe: it emits the same events the real
    orchestrator will (phase_changed, agent_turn_started, token_stream,
    agent_turn_completed, cost_update) so the frontend can be built against them now.
    """
    logger.info("starting demo session %s", session_id)
    event_bus.publish("phase_changed", {"phase": "ideation"}, session_id)

    running_in = 0
    running_out = 0

    for round_index, turn in enumerate(DEMO_SCRIPT, start=1):
        role = turn["role"]
        event_bus.publish("agent_turn_started", {"role": role, "round": 1}, session_id)

        # Stream the turn's text in small chunks with a delay, like a live model.
        for chunk in _chunk_words(str(turn["text"])):
            event_bus.publish("token_stream", {"role": role, "text": chunk}, session_id)
            await asyncio.sleep(CHUNK_DELAY_SECONDS)

        tokens_in = int(turn["tokens_in"])
        tokens_out = int(turn["tokens_out"])
        event_bus.publish(
            "agent_turn_completed",
            {"role": role, "round": 1, "usage": {"in": tokens_in, "out": tokens_out}},
            session_id,
        )

        # Accumulate and report cost so the status-bar meter visibly moves.
        running_in += tokens_in
        running_out += tokens_out
        usd = _estimate_usd(running_in, running_out)
        event_bus.publish(
            "cost_update",
            {
                "session_tokens_in": running_in,
                "session_tokens_out": running_out,
                "session_usd": round(usd, 6),
                "day_usd": round(usd, 6),
            },
            session_id,
        )
        await asyncio.sleep(TURN_GAP_SECONDS)

    logger.info("demo session %s finished", session_id)
