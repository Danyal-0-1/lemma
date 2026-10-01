"""frozen protocols and research assurance acceptance

Revision ID: 0003_research_assurance
Revises: 0002_research_workflows
Created: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_research_assurance"
down_revision: str | None = "0002_research_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("lab_runs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "input_snapshot",
                sa.JSON(),
                server_default=sa.text("'{}'"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("input_sha256", sa.String(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_lab_runs_input_sha256"), ["input_sha256"], unique=False
        )

    op.create_table(
        "lab_research_protocols",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("question", sa.String(), nullable=False),
        sa.Column("hypothesis", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("acceptance_criteria", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("project_objective", sa.String(), nullable=False),
        sa.Column("content_sha256", sa.String(), nullable=False),
        sa.Column("supersedes_id", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["lab_projects.id"]),
        sa.ForeignKeyConstraint(["supersedes_id"], ["lab_research_protocols.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "version", name="uq_lab_protocol_project_version"),
    )
    with op.batch_alter_table("lab_research_protocols", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_lab_research_protocols_content_sha256"),
            ["content_sha256"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_lab_research_protocols_project_id"),
            ["project_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_lab_research_protocols_supersedes_id"),
            ["supersedes_id"],
            unique=False,
        )

    op.create_table(
        "lab_research_assurance_acceptances",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("protocol_id", sa.String(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("confirmed_criteria", sa.JSON(), nullable=False),
        sa.Column("reviewer", sa.String(), nullable=False),
        sa.Column("notes", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["lab_projects.id"]),
        sa.ForeignKeyConstraint(["protocol_id"], ["lab_research_protocols.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["lab_runs.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["lab_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "snapshot_sha256",
            name="uq_lab_assurance_task_snapshot",
        ),
    )
    with op.batch_alter_table("lab_research_assurance_acceptances", schema=None) as batch_op:
        for column in (
            "project_id",
            "protocol_id",
            "run_id",
            "snapshot_sha256",
            "task_id",
        ):
            batch_op.create_index(
                batch_op.f(f"ix_lab_research_assurance_acceptances_{column}"),
                [column],
                unique=False,
            )


def downgrade() -> None:
    with op.batch_alter_table("lab_research_assurance_acceptances", schema=None) as batch_op:
        for column in (
            "task_id",
            "snapshot_sha256",
            "run_id",
            "protocol_id",
            "project_id",
        ):
            batch_op.drop_index(
                batch_op.f(f"ix_lab_research_assurance_acceptances_{column}")
            )
    op.drop_table("lab_research_assurance_acceptances")

    with op.batch_alter_table("lab_research_protocols", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_lab_research_protocols_supersedes_id"))
        batch_op.drop_index(batch_op.f("ix_lab_research_protocols_project_id"))
        batch_op.drop_index(batch_op.f("ix_lab_research_protocols_content_sha256"))
    op.drop_table("lab_research_protocols")

    with op.batch_alter_table("lab_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_lab_runs_input_sha256"))
        batch_op.drop_column("input_sha256")
        batch_op.drop_column("input_snapshot")
