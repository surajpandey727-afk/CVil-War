"""agent_runs — the audit trail and live-status source for Agent Ops.

One row per invocation of one named agent (Discovery, Eligibility, Scoring, ...) — see
``app.models.enums.AgentName``. Deliberately generic rather than per-agent, so every agent
writes the same shape and the Agent Ops view has one query regardless of which agent it is
inspecting.

Revision ID: b891bd8ba9e2
Revises: ab6ef2d13ebe
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b891bd8ba9e2"
down_revision: str | None = "ab6ef2d13ebe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("agent_name", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("input_summary", sa.String(length=300), nullable=True),
        sa.Column("output_summary", sa.String(length=300), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("linked_entity_type", sa.String(length=30), nullable=True),
        sa.Column("linked_entity_id", sa.String(length=64), nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("agent_runs", schema=None) as batch_op:
        batch_op.create_index(
            "ix_agent_runs_user_started", ["user_id", "started_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_agent_runs_user_id"), ["user_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_agent_runs_user_id"))
        batch_op.drop_index("ix_agent_runs_user_started")
    op.drop_table("agent_runs")
