"""Structured posting intelligence on Job.

A listing carries far more than a title and a body: the employment type, the seniority the
employer states, the function, the industry, and the requirement lines the posting actually
asks for. All of that was being discarded at parse time, so every screen that wanted to say
something specific about a role had nothing but free text to work from — and for LinkedIn,
not even that.

Kept as one JSON document rather than a dozen columns because its shape is genuinely
per-source: LinkedIn labels things its own way, Greenhouse another, and flattening them into
a fixed schema would mean inventing values none of them supplied.

Revision ID: 3f7b2c9e1a54
Revises: 0d60af14cb51
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f7b2c9e1a54"
down_revision: str | None = "0d60af14cb51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, with no server default: "never enriched" and "enriched and found nothing" are
    # different facts, and a default of {} would erase the distinction.
    op.add_column("jobs", sa.Column("posting_data", sa.JSON(), nullable=True))
    op.add_column("jobs", sa.Column("enriched_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "enriched_at")
    op.drop_column("jobs", "posting_data")
