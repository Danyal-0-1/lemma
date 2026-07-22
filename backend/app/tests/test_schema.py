# ─────────────────────────────────────────────────────────────────────────────
# test_schema.py — prove the Spec/IdeaDoc validators accept the good and reject the bad.
# READING ORDER: backend #28
#
# These validators are the safety net between "a model returned some JSON" and "we
# built a real project from it" (M5). We test both directions: a well-formed Spec
# parses, and the common failure modes (too few features, too many milestones, a
# messy slug) are handled the way we intend.
# ─────────────────────────────────────────────────────────────────────────────

import pytest
from pydantic import ValidationError

from app.ideation.schema import IdeaDoc, Spec


def _valid_spec_dict() -> dict:
    """Return a minimal, valid Spec as a plain dict (the shape a model would return)."""
    return {
        "project_name": "HabitDeck",
        "slug": "habit-deck",
        "one_liner": "A tiny daily checklist that turns streaks into a score.",
        "problem": "Progress on new habits is invisible, so people quit.",
        "target_user": "Someone building a new daily routine.",
        "core_features": [
            {"name": "Checklist", "description": "Tap to complete.", "acceptance": "Tap = done."},
            {"name": "Streak", "description": "A growing number.", "acceptance": "Complete = +1."},
            {"name": "Weekly view", "description": "Past week grid.", "acceptance": "Shows done."},
        ],
        "non_goals": ["No social features"],
        "tech_stack": {"frontend": "React", "backend": "FastAPI", "database": "SQLite"},
        "risks": ["Users forget to open it"],
        "milestones": [
            {"name": "MVP", "delivers": "Checklist persists."},
            {"name": "Streaks", "delivers": "Streak math."},
            {"name": "Weekly", "delivers": "The grid."},
        ],
        "open_questions": ["Reset at midnight or first open?"],
    }


def test_valid_spec_parses() -> None:
    """A well-formed Spec validates and defaults spec_version to 1."""
    spec = Spec.model_validate(_valid_spec_dict())
    assert spec.spec_version == 1
    assert len(spec.core_features) == 3


def test_too_few_features_rejected() -> None:
    """Fewer than 3 core features must fail validation (retry territory)."""
    bad = _valid_spec_dict()
    bad["core_features"] = bad["core_features"][:2]
    with pytest.raises(ValidationError):
        Spec.model_validate(bad)


def test_too_many_milestones_rejected() -> None:
    """More than 5 milestones must fail validation."""
    bad = _valid_spec_dict()
    bad["milestones"] = [{"name": f"M{i}", "delivers": "x"} for i in range(6)]
    with pytest.raises(ValidationError):
        Spec.model_validate(bad)


def test_slug_is_coerced_to_url_safe() -> None:
    """A messy slug is coerced (not rejected) to a url-safe form usable as a dir name."""
    spec_dict = _valid_spec_dict()
    spec_dict["slug"] = "Commit Coach!"
    spec = Spec.model_validate(spec_dict)
    assert spec.slug == "commit-coach"


def test_ideadoc_minimal_is_valid() -> None:
    """An IdeaDoc needs only a seed; ideas and notes fill in as the crew works."""
    doc = IdeaDoc(seed="a tool to track reading")
    assert doc.ideas == []
    assert doc.chosen_idea is None
