# ─────────────────────────────────────────────────────────────────────────────
# export.py — render a whole session (transcript + final Spec) as one markdown file.
# READING ORDER: backend #31
#
# WHAT THIS FILE DOES: reads a session, its messages, and its latest Spec artifact,
# and produces a single markdown document the founder can keep or hand to any coding
# agent. It reuses render_spec_markdown so the Spec looks the same everywhere.
#
# WHY export at all: the whole point of Phase 0 is to produce something portable. This
# turns the database rows into a file you own and can take anywhere.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from app.ideation import repo
from app.ideation.schema import Spec
from app.ideation.spec_render import render_spec_markdown


def render_session_markdown(session_id: str) -> str | None:
    """Return the session as a markdown string, or None if the session doesn't exist.

    Exists as the body of the export endpoint: header + the final Spec (rendered) +
    the full transcript of every role turn, in order.
    """
    session = repo.get_session_row(session_id)
    if session is None:
        return None

    messages = repo.get_messages(session_id)
    artifacts = repo.get_artifacts(session_id)
    spec_artifacts = [artifact for artifact in artifacts if artifact.kind == "spec"]

    lines: list[str] = []
    lines.append(f"# Session: {session.title}")
    lines.append("")
    lines.append(f"- **Seed:** {session.seed_prompt}")
    lines.append(f"- **Status:** {session.status}")
    lines.append(f"- **Rounds:** {session.round}")
    lines.append(f"- **Created:** {session.created_at.isoformat()}")
    lines.append("")

    # The final Spec (the most recent version), rendered human-readably.
    if spec_artifacts:
        latest_spec = Spec.model_validate_json(spec_artifacts[-1].content_json)
        lines.append("---")
        lines.append("")
        lines.append(render_spec_markdown(latest_spec))
        lines.append("")

    # The full transcript — the raw role outputs, in order. An agent can read these.
    lines.append("---")
    lines.append("")
    lines.append("## Transcript")
    lines.append("")
    for message in messages:
        lines.append(f"### {message.role.capitalize()}")
        lines.append("")
        lines.append(message.content)
        lines.append("")

    return "\n".join(lines)
