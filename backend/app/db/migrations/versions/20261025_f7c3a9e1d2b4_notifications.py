"""In-app notifications table.

Purely additive: one new table, no change to any existing table. ``kind``/``severity`` are
plain strings (no database enum types), so this runs unchanged on SQLite and PostgreSQL.
Downgrade drops the table.

Revision ID: f7c3a9e1d2b4
Revises: e5b2c8d41f07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7c3a9e1d2b4"
down_revision: str | None = "e5b2c8d41f07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="info"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("link", sa.String(300), nullable=True),
        sa.Column("entity_type", sa.String(40), nullable=True),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("dedup_key", sa.String(160), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "dedup_key", name="uq_notification_dedup"),
    )
    op.create_index("ix_notification_user_created", "notifications", ["user_id", "created_at"])
    op.create_index("ix_notification_user_unread", "notifications", ["user_id", "read_at"])
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_index("ix_notification_user_unread", table_name="notifications")
    op.drop_index("ix_notification_user_created", table_name="notifications")
    op.drop_table("notifications")
