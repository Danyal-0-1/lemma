# ─────────────────────────────────────────────────────────────────────────────
# parsing.py — pull structured JSON out of a model's free-text answer.
# READING ORDER: backend #24  (teaches: being liberal in what you accept)
#
# WHAT THIS FILE DOES:
#   Models are asked to answer with JSON inside a ```json fence. Real answers are
#   messier — extra prose, a fence without the "json" tag, or no fence at all. This
#   file extracts the JSON and validates it into our schema types. If validation
#   fails, the caller (orchestrator) retries once with the error appended.
#
# WHY separate from the orchestrator: extraction has fiddly edge cases worth isolating
#   and unit-testing on their own, away from the state-machine logic.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import re

from pydantic import TypeAdapter

from app.ideation.schema import Idea, PMOutput

# Matches a fenced code block, with or without a language tag: ```json ... ``` or ``` ... ```
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

# TypeAdapter lets us validate a JSON array (list[Idea]) without a wrapper model.
_IDEAS_ADAPTER = TypeAdapter(list[Idea])


def extract_json(text: str) -> str:
    """Return the most likely JSON substring from a model's answer.

    Exists to be forgiving: prefer a fenced block; otherwise grab from the first
    bracket to the last matching one; otherwise return the trimmed text and let the
    JSON parser produce the error. Being liberal here avoids needless retries.
    """
    fenced = _FENCE_RE.search(text)
    if fenced:
        return fenced.group(1).strip()

    # No fence: take the widest bracketed span, handling both objects and arrays.
    starts = [pos for pos in (text.find("{"), text.find("[")) if pos != -1]
    end = max(text.rfind("}"), text.rfind("]"))
    if starts and end > min(starts):
        return text[min(starts) : end + 1]

    return text.strip()


def parse_ideas(text: str) -> list[Idea]:
    """Parse a role's answer into a list of Idea (Generator/Researcher/Critic output).

    Raises pydantic ValidationError on a shape mismatch, which the orchestrator turns
    into a one-shot retry with the error fed back to the model.
    """
    return _IDEAS_ADAPTER.validate_json(extract_json(text))


def parse_pm(text: str) -> PMOutput:
    """Parse the PM's answer into a PMOutput (decision_rationale + chosen_idea + spec)."""
    return PMOutput.model_validate_json(extract_json(text))
