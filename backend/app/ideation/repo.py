# ─────────────────────────────────────────────────────────────────────────────
# repo.py — all the database reads/writes for ideation, in one place.
# READING ORDER: backend #25  (teaches: the "repository" pattern)
#
# WHAT THIS FILE DOES:
#   Wraps every SQLite operation the crew needs (create a session, save a message,
#   append an artifact, list/get for the UI) as a small, named function. The
#   orchestrator and the REST routes call THESE instead of writing SQL inline.
#
# WHY a repository: it keeps database details in one file. The orchestrator stays
#   about "what happens next"; this file is about "how it's stored." These functions
#   are synchronous (SQLite is), so async callers run them via asyncio.to_thread.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from sqlmodel import select

from app.db import get_session
from app.models import Artifact, IdeationSession, Message


def create_session(session_id: str, title: str, seed: str) -> None:
    """Insert a new IdeationSession row in the 'running' state."""
    with get_session() as db:
        db.add(IdeationSession(id=session_id, title=title, seed_prompt=seed, status="running"))
        db.commit()


def set_status(session_id: str, status: str, round_number: int | None = None) -> None:
    """Update a session's status (and optionally its round). No-op if it's gone."""
    with get_session() as db:
        session = db.get(IdeationSession, session_id)
        if session is None:
            return
        session.status = status
        if round_number is not None:
            session.round = round_number
        db.add(session)
        db.commit()


def add_message(session_id: str, role: str, content: str, tokens_in: int, tokens_out: int) -> None:
    """Append one turn's durable record (full text + token counts)."""
    with get_session() as db:
        db.add(
            Message(
                session_id=session_id,
                role=role,
                content=content,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        )
        db.commit()


def add_artifact(session_id: str, kind: str, version: int, content_json: str) -> int:
    """Append a new artifact version and return its database id.

    The id is returned because the approval gate references the Spec artifact by id in
    the `awaiting_approval` event.
    """
    with get_session() as db:
        artifact = Artifact(
            session_id=session_id, kind=kind, version=version, content_json=content_json
        )
        db.add(artifact)
        db.commit()
        db.refresh(artifact)  # populate the auto-generated id
        assert artifact.id is not None
        return artifact.id


def list_sessions() -> list[IdeationSession]:
    """Return all sessions, newest first — for the sidebar history (M4)."""
    with get_session() as db:
        return list(db.exec(select(IdeationSession).order_by(IdeationSession.created_at.desc())))


def get_session_row(session_id: str) -> IdeationSession | None:
    """Return one session by id, or None."""
    with get_session() as db:
        return db.get(IdeationSession, session_id)


def get_messages(session_id: str) -> list[Message]:
    """Return a session's messages in order — for restore/export (M4)."""
    with get_session() as db:
        return list(
            db.exec(
                select(Message).where(Message.session_id == session_id).order_by(Message.id)
            )
        )


def get_artifacts(session_id: str) -> list[Artifact]:
    """Return a session's artifacts in save order — for the Spec tab (M4)."""
    with get_session() as db:
        return list(
            db.exec(
                select(Artifact).where(Artifact.session_id == session_id).order_by(Artifact.id)
            )
        )


def get_artifact_by_id(artifact_id: int) -> Artifact | None:
    """Return one artifact by its database id — used when building a workspace (M5)."""
    with get_session() as db:
        return db.get(Artifact, artifact_id)
