"""communication_events — inbound/outbound comms not yet confidently matched to an application.

A high-confidence Gmail reply or Apollo contact writes straight onto the matched
application's own timeline (``application_events``); this table exists only for the ones
inbox-sync/apollo-sync could not confidently attribute — see ``app.models.communication_event``.

Revision ID: c4d1e8f39a27
Revises: b891bd8ba9e2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d1e8f39a27"
down_revision: str | None = "b891bd8ba9e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "communication_events",
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("application_id", sa.String(length=32), nullable=True),
        sa.Column("sender", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("subject", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column(
            "matched_confidence", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column("classified_as", sa.String(length=30), nullable=False, server_default=""),
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
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "source", "external_id", name="uq_communication_event"
        ),
    )
    with op.batch_alter_table("communication_events", schema=None) as batch_op:
        batch_op.create_index(
            "ix_communication_event_user_occurred", ["user_id", "occurred_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_communication_events_user_id"), ["user_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("communication_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_communication_events_user_id"))
        batch_op.drop_index("ix_communication_event_user_occurred")
    op.drop_table("communication_events")
