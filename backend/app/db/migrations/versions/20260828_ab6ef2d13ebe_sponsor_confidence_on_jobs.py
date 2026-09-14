"""Sponsor confidence on Job — a ranking boost, never a hard filter.

Two signals feed this: a match on the UK Home Office's public register of licensed Skilled
Worker sponsors, and explicit sponsorship language in the posting text. See
``core.sponsorship`` for the classifier; ``services.job_search.list_jobs`` reads this to rank
sponsor-confirmed roles above equal non-sponsor roles without ever excluding the latter.

Revision ID: ab6ef2d13ebe
Revises: 3f7b2c9e1a54
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ab6ef2d13ebe"
down_revision: str | None = "3f7b2c9e1a54"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "sponsor_confidence",
            sa.String(length=30),
            nullable=False,
            server_default="unknown",
        ),
    )
    # Nullable, no default: UNKNOWN has nothing to show, which is different from a fact that
    # was hidden — the same reasoning posting_data/enriched_at already follow on this table.
    op.add_column("jobs", sa.Column("sponsor_evidence", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "sponsor_evidence")
    op.drop_column("jobs", "sponsor_confidence")
