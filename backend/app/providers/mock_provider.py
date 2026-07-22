# ─────────────────────────────────────────────────────────────────────────────
# mock_provider.py — zero-cost canned streams (MOCK_LLM=true, the default).
# READING ORDER: backend #13
#
# WHAT THIS FILE DOES:
#   Implements the SAME ModelProvider interface as the real one, but streams canned
#   text with small delays instead of calling an API — so the whole app runs with no
#   keys and no cost (PROMPT.md §13). It peeks at the system prompt to pick output
#   that fits the asking role, so a mock run "feels" like a real debate.
#
#   For the M3 crew, each role is asked for JSON, so the mock returns schema-valid
#   JSON (in a ```json fence) that the orchestrator can parse. For the M2 "one real
#   turn" (which asks for markdown prose), the mock returns prose instead. It tells
#   them apart by whether the prompt asks for JSON.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.providers.base import ChatMessage, StreamDone, StreamEvent, TextDelta, Usage

# Delay between streamed chunks, so mock output visibly "types" like a live model.
CHUNK_DELAY_SECONDS = 0.02

# --- Canned JSON for the M3 crew (each is one ```json fenced block) -----------

_GENERATOR_JSON = """```json
[
  {"name": "HabitDeck", "pitch": "A tiny daily checklist that turns streaks into a visible score. For anyone building a new routine who wants lightweight momentum."},
  {"name": "NudgeBot", "pitch": "Sends one well-timed reminder a day based on gaps in your calendar. For busy people who forget their own goals."},
  {"name": "WhyLog", "pitch": "A 20-second end-of-day journal that surfaces weekly patterns. For reflective people who want insight without effort."}
]
```"""

_RESEARCHER_JSON = """```json
[
  {"name": "HabitDeck", "pitch": "A tiny daily checklist that turns streaks into a visible score.", "feasibility_notes": "Many streak apps exist, but a fridge-simple score is a gap. Hard part: streak edge cases across time zones. Scope: weeks."},
  {"name": "NudgeBot", "pitch": "One well-timed reminder a day based on calendar gaps.", "feasibility_notes": "Calendar parsing is the tricky bit; the rest is a scheduler plus a message. Scope: weeks."},
  {"name": "WhyLog", "pitch": "A 20-second end-of-day journal that surfaces weekly patterns.", "feasibility_notes": "Journaling apps abound; the weekly-pattern summary is the differentiator. Scope: weekend."}
]
```"""

_CRITIC_JSON = """```json
[
  {"name": "HabitDeck", "pitch": "A tiny daily checklist that turns streaks into a visible score.", "feasibility_notes": "Fridge-simple score is a gap. Scope: weeks.", "critic_notes": "Retention risk: who opens a checklist daily? Make the score the hook. Verdict: PURSUE - risk: forming the habit of using it."},
  {"name": "NudgeBot", "pitch": "One well-timed reminder a day based on calendar gaps.", "feasibility_notes": "Calendar parsing is the tricky bit. Scope: weeks.", "critic_notes": "Just one more notification people will mute. Verdict: RESHAPE - risk: notification fatigue."},
  {"name": "WhyLog", "pitch": "A 20-second end-of-day journal that surfaces weekly patterns.", "feasibility_notes": "Weekly summary is the differentiator. Scope: weekend.", "critic_notes": "Value hinges entirely on the summary being insightful. Verdict: RESHAPE - risk: shallow summaries."}
]
```"""

_PM_JSON = """```json
{
  "decision_rationale": "HabitDeck is the one a beginner can finish and use daily. The critic's retention risk is answered by making the streak score the whole point, not a side feature.",
  "chosen_idea": "HabitDeck",
  "spec": {
    "spec_version": 1,
    "project_name": "HabitDeck",
    "slug": "habit-deck",
    "one_liner": "A tiny daily checklist that turns streaks into a visible score.",
    "problem": "People start habits and quietly abandon them because progress is invisible.",
    "target_user": "Someone building a new daily routine who wants lightweight accountability.",
    "core_features": [
      {"name": "Daily checklist", "description": "Check off today's habits in one tap.", "acceptance": "Given today's habits, when I tap one, then it is marked done and the streak updates."},
      {"name": "Streak score", "description": "A visible number that grows with consecutive days.", "acceptance": "Given a 3-day streak, when I complete today, then the score reads 4."},
      {"name": "Weekly view", "description": "See the past week at a glance.", "acceptance": "Given a week of data, when I open the weekly view, then each day shows done or missed."}
    ],
    "non_goals": ["No social features", "No native mobile app in v1"],
    "tech_stack": {"frontend": "React + Vite", "backend": "FastAPI", "database": "SQLite", "other": null},
    "risks": ["Users forget to open it", "Streak anxiety could backfire"],
    "milestones": [
      {"name": "Checklist MVP", "delivers": "Add habits and check them off, persisted to the database."},
      {"name": "Streaks", "delivers": "Streak calculation and the score display."},
      {"name": "Weekly view", "delivers": "The 7-day grid and basic stats."}
    ],
    "open_questions": ["Should streaks reset at local midnight or on first open of the day?"]
  }
}
```"""

# --- Canned prose (for the M2 oneshot and the M7 mentor) ----------------------

_GENERATOR_PROSE = (
    "Here are three concrete directions for your seed:\n\n"
    "1. **HabitDeck** - a tiny daily checklist that turns streaks into a visible score.\n"
    "2. **NudgeBot** - sends one well-timed reminder a day based on your calendar gaps.\n"
    "3. **WhyLog** - a 20-second end-of-day journal that surfaces patterns weekly.\n\n"
    "All three are buildable solo in a couple of weeks."
)

_MENTOR_PROSE = (
    "**In plain words:** this code streams events to the browser over one WebSocket.\n\n"
    "**Key lines:** the envelope carries a `seq` so the client can spot dropped frames; "
    "the bus fans one publish out to every connection.\n\n"
    "**Why this way:** decoupling 'something happened' from 'send it' means features "
    "never touch sockets — they just `publish`.\n\n"
    "**Try this:** add a new event name and watch it flow end to end."
)

_DEFAULT_CANNED = (
    "This is a mock response. Set `MOCK_LLM=false` and add a provider key in "
    "`backend/.env` to stream real model output here."
)


def _pick_canned(messages: list[ChatMessage]) -> str:
    """Choose canned output that fits the asking role (and the requested format).

    Exists so a mock run mirrors a real one: JSON for the crew roles that need it,
    prose for the oneshot/mentor. Detection is by distinctive phrases in the system
    prompt, which keeps it robust to small wording changes.
    """
    system_text = " ".join(m.content for m in messages if m.role == "system").lower()
    wants_json = "json" in system_text  # the M3 role prompts explicitly ask for JSON

    if "you are the researcher" in system_text:
        return _RESEARCHER_JSON
    if "you are the critic" in system_text:
        return _CRITIC_JSON
    if "you are the pm" in system_text:
        return _PM_JSON
    if "you are the generator" in system_text:
        return _GENERATOR_JSON if wants_json else _GENERATOR_PROSE
    if "mentor" in system_text:
        return _MENTOR_PROSE
    return _DEFAULT_CANNED


def _chunk_words(text: str, words_per_chunk: int = 4) -> list[str]:
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
