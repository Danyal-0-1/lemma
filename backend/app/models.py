# ─────────────────────────────────────────────────────────────────────────────
# models.py — the database tables (SQLModel).
# READING ORDER: backend #16
#
# WHAT THIS FILE DOES: defines the rows we persist to SQLite. SQLModel classes with
# `table=True` are BOTH a pydantic model (validation) and a database table (storage)
# in one declaration — which is why we use it here.
#
# WHY these tables: they let a session survive a reload — you can watch an idea
# evolve (Artifact is append-only) and restore past runs. We add tables over time and
# recreate the DB in dev; there are no migrations in v1 (§8).
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return the current UTC time — the default timestamp for new rows."""
    return datetime.now(UTC)


class IdeationSession(SQLModel, table=True):
    """One ideation run: its seed, its status, and which round it's on.

    Exists so a session is durable — listable in the sidebar and restorable after a
    reload. The id IS the string session_id used across events (e.g. "ideation_9f3a").
    """

    id: str = Field(primary_key=True)
    title: str
    seed_prompt: str
    # running | awaiting_approval | approved | rejected | cancelled | budget_stopped
    status: str = "running"
    round: int = 0
    created_at: datetime = Field(default_factory=_utcnow)


class Message(SQLModel, table=True):
    """One turn's full text plus its token counts, kept for history and export.

    Exists so the transcript can be replayed and exported later (M4) — the streamed
    tokens are ephemeral; this is the durable record.
    """

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    role: str
    content: str
    tokens_in: int = 0
    tokens_out: int = 0
    created_at: datetime = Field(default_factory=_utcnow)


class Artifact(SQLModel, table=True):
    """One saved version of an IdeaDoc or Spec. APPEND-ONLY.

    Exists so nothing is overwritten: each save is a new row with the next version
    number, so the founder can scrub through how the idea (and Spec) evolved (§8).
    """

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    kind: str  # "ideadoc" | "spec"
    version: int
    content_json: str  # the serialized IdeaDoc/Spec
    created_at: datetime = Field(default_factory=_utcnow)


class CostRecord(SQLModel, table=True):
    """One priced model call: which session, which model, how many tokens, what cost.

    Exists so the cost meter can be summed from durable history (per session and per
    day) rather than living only in memory. Append-only in spirit: we insert one row
    per completed turn and never mutate it.
    """

    id: int | None = Field(default=None, primary_key=True)
    # Which ideation/oneshot session this spend belongs to (indexed for fast summing).
    session_id: str = Field(index=True)
    model: str
    tokens_in: int
    tokens_out: int
    usd: float
    created_at: datetime = Field(default_factory=_utcnow)
