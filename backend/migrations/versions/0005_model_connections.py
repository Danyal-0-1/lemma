"""persist model connection selection and call provenance

Revision ID: 0005_model_connections
Revises: 0004_research_assurance_hardening
Created: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_model_connections"
down_revision: str | None = "0004_research_assurance_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("lab_agents", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "model_connection",
                sa.String(),
                server_default="legacy",
                nullable=False,
            )
        )

    with op.batch_alter_table("lab_model_calls", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "connection_id",
                sa.String(),
                server_default="legacy",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "connection_snapshot",
                sa.JSON(),
                server_default=sa.text("'{}'"),
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("lab_model_calls", schema=None) as batch_op:
        batch_op.drop_column("connection_snapshot")
        batch_op.drop_column("connection_id")

    with op.batch_alter_table("lab_agents", schema=None) as batch_op:
        batch_op.drop_column("model_connection")
