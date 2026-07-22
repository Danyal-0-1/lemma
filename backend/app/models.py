# ─────────────────────────────────────────────────────────────────────────────
# models.py — the database tables (SQLModel).
# READING ORDER: backend #16
#
# WHAT THIS FILE DOES: defines the rows we persist to SQLite. SQLModel classes with
# `table=True` are BOTH a pydantic model (validation) and a database table (storage)
# in one declaration — which is why we use it here.
#
# WHY start with just CostRecord: M2 needs to remember spend so the cost meter is
# real, not just a live number that vanishes on reload. The session/message/artifact
# tables join this file in M3 (we recreate tables in dev — no migrations, per §8).
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return the current UTC time — the default timestamp for new rows."""
    return datetime.now(UTC)


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
