# ─────────────────────────────────────────────────────────────────────────────
# spec_render.py — turn a Spec into human-readable markdown.
# READING ORDER: backend #30
#
# WHAT THIS FILE DOES: renders a Spec object as a clean markdown document. It's used
# by the session export (M4) and — importantly — by the workspace scaffold in M5,
# which writes this exact render to SPEC.md for the coding agent to read.
#
# WHY one shared renderer: the Spec should look the same wherever it appears, and
# keeping the formatting in one function means we only get it right once.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from app.ideation.schema import Spec


def render_spec_markdown(spec: Spec) -> str:
    """Return `spec` as a readable markdown document (used by export and SPEC.md).

    Exists so the Spec renders identically in the export file and the workspace's
    SPEC.md, from a single, testable place.
    """
    lines: list[str] = []
    lines.append(f"# {spec.project_name}")
    lines.append("")
    lines.append(f"> {spec.one_liner}")
    lines.append("")
    lines.append(f"**Slug:** `{spec.slug}`")
    lines.append("")

    lines.append("## Problem")
    lines.append(spec.problem)
    lines.append("")

    lines.append("## Target user")
    lines.append(spec.target_user)
    lines.append("")

    lines.append("## Core features")
    for feature in spec.core_features:
        lines.append(f"### {feature.name}")
        lines.append(feature.description)
        lines.append(f"_Acceptance:_ {feature.acceptance}")
        lines.append("")

    if spec.non_goals:
        lines.append("## Non-goals")
        lines.extend(f"- {item}" for item in spec.non_goals)
        lines.append("")

    lines.append("## Tech stack")
    for label, value in (
        ("Frontend", spec.tech_stack.frontend),
        ("Backend", spec.tech_stack.backend),
        ("Database", spec.tech_stack.database),
        ("Other", spec.tech_stack.other),
    ):
        if value:
            lines.append(f"- **{label}:** {value}")
    lines.append("")

    if spec.risks:
        lines.append("## Risks")
        lines.extend(f"- {item}" for item in spec.risks)
        lines.append("")

    lines.append("## Milestones")
    for index, milestone in enumerate(spec.milestones, start=1):
        lines.append(f"{index}. **{milestone.name}** — {milestone.delivers}")
    lines.append("")

    if spec.open_questions:
        lines.append("## Open questions")
        lines.extend(f"- {item}" for item in spec.open_questions)
        lines.append("")

    return "\n".join(lines)
