# ─────────────────────────────────────────────────────────────────────────────
# schema.py — the data the crew produces: the IdeaDoc and the Spec.
# READING ORDER: backend #22  ← RETYPE THIS (M3)
#
# WHAT THIS FILE DOES:
#   Defines the two artifacts the ideation crew builds up:
#     • IdeaDoc — the evolving list of ideas with researcher/critic notes,
#     • Spec    — the final, build-ready blueprint the founder approves.
#   These are strict pydantic models with validators, so a model's JSON is only
#   accepted if it actually fits the shape — and if it doesn't, the orchestrator
#   gets a precise error to feed back to the model on retry.
#
# WHY strict validation here matters: the Spec becomes a real workspace in M5. A
#   bad slug or too-few features would break that later, so we catch it now, at the
#   boundary, where the fix is cheap.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import re

from pydantic import BaseModel, field_validator

# A url-safe slug: lowercase words joined by single hyphens (e.g. "commit-coach").
_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Bounds from PROMPT.md §8. Kept as constants so the numbers have names.
MIN_FEATURES = 3
MAX_FEATURES = 7
MIN_MILESTONES = 3
MAX_MILESTONES = 5


class Idea(BaseModel):
    """One candidate project idea, annotated as it moves through the crew.

    Exists as the unit the Generator creates and the Researcher/Critic enrich. The
    notes are optional because they're filled in later stages, not up front.
    """

    name: str
    pitch: str
    feasibility_notes: str | None = None
    critic_notes: str | None = None


class IdeaDoc(BaseModel):
    """The evolving idea document — the crew's shared scratchpad.

    Exists so each role reads the same running context and the founder can watch the
    idea evolve (each saved version is a new Artifact row).
    """

    seed: str
    ideas: list[Idea] = []
    decision_rationale: str | None = None
    chosen_idea: str | None = None


class Feature(BaseModel):
    """One core feature: what it is and how you'd know it works."""

    name: str
    description: str
    acceptance: str  # a concrete acceptance criterion (given/when/then works well)


class TechStack(BaseModel):
    """The chosen technologies. All optional — small projects don't use every slot."""

    frontend: str | None = None
    backend: str | None = None
    database: str | None = None
    other: str | None = None


class Milestone(BaseModel):
    """One build milestone: its name and what shipping it delivers."""

    name: str
    delivers: str


class Spec(BaseModel):
    """The approved, build-ready blueprint — the crew's final output.

    Exists as the contract handed to the coding agent in M5. Versioned via
    `spec_version` so the shape can evolve without silently misreading old specs.
    """

    spec_version: int = 1
    project_name: str
    slug: str
    one_liner: str
    problem: str
    target_user: str
    core_features: list[Feature]
    non_goals: list[str] = []
    tech_stack: TechStack
    risks: list[str] = []
    milestones: list[Milestone]
    open_questions: list[str] = []

    @field_validator("slug")
    @classmethod
    def _coerce_urlsafe_slug(cls, value: str) -> str:
        """Force the slug into a url-safe form (lowercase, hyphen-separated).

        We COERCE rather than reject, because a real model may return "Commit Coach"
        or "commit_coach" — turning that into "commit-coach" is safer than failing the
        whole Spec, and the result is guaranteed usable as a directory name in M5.
        """
        cleaned = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
        if not cleaned:
            raise ValueError("slug is empty after removing non-url-safe characters")
        return cleaned

    @field_validator("core_features")
    @classmethod
    def _features_within_bounds(cls, value: list[Feature]) -> list[Feature]:
        """Require 3-7 core features — enough to be real, few enough to be buildable."""
        if not (MIN_FEATURES <= len(value) <= MAX_FEATURES):
            raise ValueError(
                f"core_features must have {MIN_FEATURES}-{MAX_FEATURES} items, got {len(value)}"
            )
        return value

    @field_validator("milestones")
    @classmethod
    def _milestones_within_bounds(cls, value: list[Milestone]) -> list[Milestone]:
        """Require 3-5 milestones — a realistic solo build plan, not a wishlist."""
        if not (MIN_MILESTONES <= len(value) <= MAX_MILESTONES):
            raise ValueError(
                f"milestones must have {MIN_MILESTONES}-{MAX_MILESTONES} items, got {len(value)}"
            )
        return value


class PMOutput(BaseModel):
    """The PM's structured output: the decision plus the full Spec.

    Exists because the PM does two things at once — justify a choice and produce the
    Spec — and we validate both in one parse (PROMPT.md §9).
    """

    decision_rationale: str
    chosen_idea: str
    spec: Spec
