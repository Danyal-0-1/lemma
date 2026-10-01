"""forward-compatible research assurance hardening

Revision ID: 0004_research_assurance_hardening
Revises: 0003_research_assurance
Created: 2026-09-30

This revision is intentionally defensive. Early development builds applied revision
0003 before the immutable run/acceptance snapshot columns were finalized. A normal
fresh 0003 database already has every field, while those databases need the missing
pieces added without deleting or restamping user data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_research_assurance_hardening"
down_revision: str | None = "0003_research_assurance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    run_columns = _columns("lab_runs")
    with op.batch_alter_table("lab_runs", schema=None) as batch_op:
        if "input_snapshot" not in run_columns:
            batch_op.add_column(
                sa.Column(
                    "input_snapshot",
                    sa.JSON(),
                    server_default=sa.text("'{}'"),
                    nullable=False,
                )
            )
        if "input_sha256" not in run_columns:
            batch_op.add_column(sa.Column("input_sha256", sa.String(), nullable=True))

    run_indexes = {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes("lab_runs")
    }
    if "ix_lab_runs_input_sha256" not in run_indexes:
        with op.batch_alter_table("lab_runs", schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f("ix_lab_runs_input_sha256"),
                ["input_sha256"],
                unique=False,
            )

    acceptance_table = "lab_research_assurance_acceptances"
    acceptance_columns = _columns(acceptance_table)
    with op.batch_alter_table(acceptance_table, schema=None) as batch_op:
        if "snapshot_json" not in acceptance_columns:
            batch_op.add_column(
                sa.Column(
                    "snapshot_json",
                    sa.JSON(),
                    server_default=sa.text("'{}'"),
                    nullable=False,
                )
            )
        if "confirmed_criteria" not in acceptance_columns:
            batch_op.add_column(
                sa.Column(
                    "confirmed_criteria",
                    sa.JSON(),
                    server_default=sa.text("'[]'"),
                    nullable=False,
                )
            )

    unique_names = {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(acceptance_table)
    }
    if "uq_lab_assurance_task_snapshot" not in unique_names:
        duplicate = op.get_bind().execute(
            sa.text(
                "SELECT 1 FROM lab_research_assurance_acceptances "
                "GROUP BY task_id, snapshot_sha256 HAVING COUNT(*) > 1 LIMIT 1"
            )
        ).first()
        if duplicate is None:
            with op.batch_alter_table(acceptance_table, schema=None) as batch_op:
                batch_op.create_unique_constraint(
                    "uq_lab_assurance_task_snapshot",
                    ["task_id", "snapshot_sha256"],
                )


def downgrade() -> None:
    # Forward-only compatibility shim: 0003 owns these columns on a fresh database.
    # Keeping them is both lossless and lets a subsequent downgrade of 0003 remove
    # its tables/columns in the normal order.
    pass
