"""Adopt the complete Lemma 0.2 schema as the migration baseline.

Revision ID: 0001_current_schema
Revises: None
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_current_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table(name: str, *columns: sa.Column[object]) -> None:
    """Create a baseline table, or safely adopt its legacy create_all version."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(name):
        present = {column["name"] for column in inspector.get_columns(name)}
        required = {column.name for column in columns if isinstance(column, sa.Column)}
        missing = sorted(required - present)
        if missing:
            raise RuntimeError(
                f"cannot adopt legacy table {name!r}; missing columns: {', '.join(missing)}"
            )
        return
    op.create_table(name, *columns)


def _index(name: str, table: str, columns: list[str]) -> None:
    """Create indexes absent from a legacy create_all database."""
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=False)


def upgrade() -> None:
    _table(
        "artifact",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("ix_artifact_session_id", "artifact", ["session_id"])

    _table(
        "costrecord",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("usd", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("ix_costrecord_session_id", "costrecord", ["session_id"])

    _table(
        "ideationsession",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("seed_prompt", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    _table(
        "lab_activity",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("action", "agent_id", "entity_id", "entity_type", "run_id"):
        _index(f"ix_lab_activity_{column}", "lab_activity", [column])

    _table(
        "lab_departments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("ix_lab_departments_name", "lab_departments", ["name"])

    _table(
        "lab_projects",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("objective", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("ix_lab_projects_name", "lab_projects", ["name"])

    _table(
        "message",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("ix_message_session_id", "message", ["session_id"])

    _table(
        "workspace",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("spec_artifact_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    _table(
        "lab_agents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("department_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("mission", sa.String(), nullable=False),
        sa.Column("duties", sa.JSON(), nullable=False),
        sa.Column("focus", sa.JSON(), nullable=False),
        sa.Column("priorities", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("communication_scope", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["lab_departments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("ix_lab_agents_department_id", "lab_agents", ["department_id"])
    _index("ix_lab_agents_name", "lab_agents", ["name"])

    _table(
        "lab_meetings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("department_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("agenda", sa.String(), nullable=False),
        sa.Column("facilitator_agent_id", sa.String(), nullable=False),
        sa.Column("participant_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["lab_departments.id"]),
        sa.ForeignKeyConstraint(["facilitator_agent_id"], ["lab_agents.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["lab_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("department_id", "facilitator_agent_id", "project_id"):
        _index(f"ix_lab_meetings_{column}", "lab_meetings", [column])

    _table(
        "lab_tasks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("department_id", sa.String(), nullable=True),
        sa.Column("assigned_agent_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("objective", sa.String(), nullable=False),
        sa.Column("context", sa.String(), nullable=False),
        sa.Column("expected_output", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["assigned_agent_id"], ["lab_agents.id"]),
        sa.ForeignKeyConstraint(["department_id"], ["lab_departments.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["lab_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("assigned_agent_id", "department_id", "project_id"):
        _index(f"ix_lab_tasks_{column}", "lab_tasks", [column])

    _table(
        "lab_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("meeting_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["meeting_id"], ["lab_meetings.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["lab_projects.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["lab_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("meeting_id", "project_id", "task_id"):
        _index(f"ix_lab_runs_{column}", "lab_runs", [column])

    _table(
        "lab_meeting_messages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("meeting_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["lab_agents.id"]),
        sa.ForeignKeyConstraint(["meeting_id"], ["lab_meetings.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["lab_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("agent_id", "meeting_id", "run_id"):
        _index(f"ix_lab_meeting_messages_{column}", "lab_meeting_messages", [column])

    _table(
        "lab_task_results",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["lab_agents.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["lab_projects.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["lab_runs.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["lab_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("agent_id", "project_id", "run_id", "task_id"):
        _index(f"ix_lab_task_results_{column}", "lab_task_results", [column])

    _table(
        "lab_findings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("result_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["lab_agents.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["lab_projects.id"]),
        sa.ForeignKeyConstraint(["result_id"], ["lab_task_results.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["lab_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("agent_id", "project_id", "result_id", "task_id"):
        _index(f"ix_lab_findings_{column}", "lab_findings", [column])


def downgrade() -> None:
    for table in (
        "lab_findings",
        "lab_task_results",
        "lab_meeting_messages",
        "lab_runs",
        "lab_tasks",
        "lab_meetings",
        "lab_agents",
        "workspace",
        "message",
        "lab_projects",
        "lab_departments",
        "lab_activity",
        "ideationsession",
        "costrecord",
        "artifact",
    ):
        op.drop_table(table)
