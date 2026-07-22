# ─────────────────────────────────────────────────────────────────────────────
# test_export.py — prove the Spec renders to clean, complete markdown.
# READING ORDER: backend #32
#
# render_spec_markdown is reused for both the session export and the M5 SPEC.md, so a
# small test that it includes every section pays off twice.
# ─────────────────────────────────────────────────────────────────────────────

from app.ideation.schema import Spec
from app.ideation.spec_render import render_spec_markdown


def _spec() -> Spec:
    return Spec.model_validate(
        {
            "project_name": "HabitDeck",
            "slug": "habit-deck",
            "one_liner": "A tiny daily checklist that turns streaks into a score.",
            "problem": "Progress is invisible, so people quit.",
            "target_user": "Someone building a new routine.",
            "core_features": [
                {"name": "Checklist", "description": "Tap to done.", "acceptance": "Tap = done."},
                {"name": "Streak", "description": "A number.", "acceptance": "Complete = +1."},
                {"name": "Weekly", "description": "Week grid.", "acceptance": "Shows done."},
            ],
            "non_goals": ["No social"],
            "tech_stack": {"frontend": "React", "backend": "FastAPI", "database": "SQLite"},
            "risks": ["Users forget"],
            "milestones": [
                {"name": "MVP", "delivers": "Checklist persists."},
                {"name": "Streaks", "delivers": "Streak math."},
                {"name": "Weekly", "delivers": "The grid."},
            ],
            "open_questions": ["Reset when?"],
        }
    )


def test_render_includes_all_sections() -> None:
    """The rendered markdown has the title, the one-liner, and every major section."""
    text = render_spec_markdown(_spec())

    assert "# HabitDeck" in text
    assert "> A tiny daily checklist" in text
    assert "## Problem" in text
    assert "## Core features" in text
    assert "### Checklist" in text
    assert "_Acceptance:_ Tap = done." in text
    assert "## Milestones" in text
    assert "1. **MVP**" in text
    assert "## Open questions" in text
