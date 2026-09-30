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
from uuid import uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return the current UTC time — the default timestamp for new rows."""
    return datetime.now(UTC)


def _uuid() -> str:
    """Return a full random UUID string for durable public identifiers."""
    return str(uuid4())


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


class Workspace(SQLModel, table=True):
    """One build project: a real directory on disk created from an approved Spec.

    Exists so a workspace survives restarts — listable in the sidebar, reopenable, and
    (M8) archivable. The directory is never deleted in v1; archiving just flips status.
    """

    id: str = Field(primary_key=True)  # e.g. "ws_1a2b3c4d"
    slug: str
    path: str  # absolute path to the workspace directory
    spec_artifact_id: int  # which Spec artifact this was built from
    status: str = "active"  # active | archived
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


# ── Research lab domain ------------------------------------------------------
#
# These tables generalize Lemma's original fixed four-role ideation crew into a
# configurable research organization. JSON columns are used only for small bounded
# lists (duties, participants, citations, audit details); durable conversational
# content still gets its own row so it can be addressed, ordered, and audited.


class Department(SQLModel, table=True):
    """A stable department or a temporary cross-functional mission team."""

    __tablename__ = "lab_departments"

    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str = Field(index=True)
    description: str = ""
    kind: str = "department"  # department | mission_team
    status: str = "active"  # active | archived
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class LabAgent(SQLModel, table=True):
    """One user-defined research agent and its bounded operating charter."""

    __tablename__ = "lab_agents"

    id: str = Field(default_factory=_uuid, primary_key=True)
    department_id: str | None = Field(default=None, foreign_key="lab_departments.id", index=True)
    name: str = Field(index=True)
    role: str
    mission: str
    duties: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    focus: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    priorities: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    model: str
    status: str = "active"  # active | paused | archived
    communication_scope: str = "department"  # isolated | department | organization
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ResearchProject(SQLModel, table=True):
    """A research objective that groups tasks, findings, and meetings."""

    __tablename__ = "lab_projects"

    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str = Field(index=True)
    description: str = ""
    objective: str
    status: str = "active"  # draft | active | completed | archived
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ResearchTask(SQLModel, table=True):
    """A bounded assignment for one agent inside a research project."""

    __tablename__ = "lab_tasks"

    id: str = Field(default_factory=_uuid, primary_key=True)
    project_id: str = Field(foreign_key="lab_projects.id", index=True)
    department_id: str | None = Field(default=None, foreign_key="lab_departments.id", index=True)
    assigned_agent_id: str = Field(foreign_key="lab_agents.id", index=True)
    title: str
    objective: str
    context: str = ""
    expected_output: str = ""
    status: str = "queued"  # queued | running | completed | failed | cancelled
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class LabRun(SQLModel, table=True):
    """One durable task or meeting execution, including usage and terminal state."""

    __tablename__ = "lab_runs"

    id: str = Field(default_factory=_uuid, primary_key=True)
    kind: str  # task | meeting
    project_id: str = Field(foreign_key="lab_projects.id", index=True)
    task_id: str | None = Field(default=None, foreign_key="lab_tasks.id", index=True)
    meeting_id: str | None = Field(default=None, foreign_key="lab_meetings.id", index=True)
    status: str = "running"  # running | completed | failed | cancelled
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None


class TaskResult(SQLModel, table=True):
    """The full model-produced result from one completed research task run."""

    __tablename__ = "lab_task_results"

    id: str = Field(default_factory=_uuid, primary_key=True)
    project_id: str = Field(foreign_key="lab_projects.id", index=True)
    task_id: str = Field(foreign_key="lab_tasks.id", index=True)
    run_id: str = Field(foreign_key="lab_runs.id", index=True)
    agent_id: str = Field(foreign_key="lab_agents.id", index=True)
    content: str
    created_at: datetime = Field(default_factory=_utcnow)


class Finding(SQLModel, table=True):
    """A reviewable research finding with provenance back to its task result."""

    __tablename__ = "lab_findings"

    id: str = Field(default_factory=_uuid, primary_key=True)
    project_id: str = Field(foreign_key="lab_projects.id", index=True)
    task_id: str = Field(foreign_key="lab_tasks.id", index=True)
    result_id: str = Field(foreign_key="lab_task_results.id", index=True)
    agent_id: str = Field(foreign_key="lab_agents.id", index=True)
    title: str
    content: str
    confidence: float | None = None
    citations: list[dict[str, str]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=_utcnow)


class ResearchMeeting(SQLModel, table=True):
    """A bounded room where configured participants contribute once, then synthesize."""

    __tablename__ = "lab_meetings"

    id: str = Field(default_factory=_uuid, primary_key=True)
    project_id: str = Field(foreign_key="lab_projects.id", index=True)
    department_id: str | None = Field(default=None, foreign_key="lab_departments.id", index=True)
    title: str
    agenda: str
    facilitator_agent_id: str = Field(foreign_key="lab_agents.id", index=True)
    participant_ids: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    status: str = "planned"  # planned | running | completed | failed | cancelled
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class MeetingMessage(SQLModel, table=True):
    """One persisted participant contribution or facilitator synthesis."""

    __tablename__ = "lab_meeting_messages"

    id: str = Field(default_factory=_uuid, primary_key=True)
    meeting_id: str = Field(foreign_key="lab_meetings.id", index=True)
    run_id: str = Field(foreign_key="lab_runs.id", index=True)
    agent_id: str = Field(foreign_key="lab_agents.id", index=True)
    kind: str  # contribution | synthesis
    ordinal: int
    content: str
    created_at: datetime = Field(default_factory=_utcnow)


class ActivityRecord(SQLModel, table=True):
    """An append-only audit/activity row for important research-lab actions."""

    __tablename__ = "lab_activity"

    id: str = Field(default_factory=_uuid, primary_key=True)
    action: str = Field(index=True)
    entity_type: str = Field(index=True)
    entity_id: str = Field(index=True)
    run_id: str | None = Field(default=None, index=True)
    agent_id: str | None = Field(default=None, index=True)
    details: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=_utcnow)
