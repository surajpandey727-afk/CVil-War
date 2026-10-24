"""Normalised job location fields for the UK-only policy.

Adds the columns :mod:`app.core.geo.classify` writes. Every column is nullable or has a
literal server default, and none is an enum, so this runs unchanged on SQLite and on a fresh
PostgreSQL (the two failure modes earlier migrations hit there: enum types never created, and
unquoted text defaults). Existing rows start ``uk_eligible = false`` with a NULL status — "not
classified yet" — and are classified by ``services.job_location.classify_pending``, which the
jobs list runs before reading, so no row is shown before it has been checked.

Purely additive: downgrade drops the columns and the raw ``location`` text is untouched.

Revision ID: e5b2c8d41f07
Revises: a3d9c51e7b20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5b2c8d41f07"
down_revision: str | None = "a3d9c51e7b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    sa.Column("country_code", sa.String(2), nullable=True),
    sa.Column("country_name", sa.String(80), nullable=True),
    sa.Column("city", sa.String(120), nullable=True),
    sa.Column("region", sa.String(120), nullable=True),
    sa.Column("workplace_type", sa.String(16), nullable=True),
    sa.Column("remote_eligible_countries", sa.JSON(), nullable=True),
    sa.Column("location_verification_status", sa.String(16), nullable=True),
    sa.Column("location_evidence_source", sa.String(40), nullable=True),
    sa.Column("location_verified_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("uk_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
)


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        for column in _COLUMNS:
            batch.add_column(column.copy())
    op.create_index("ix_job_uk_eligible", "jobs", ["user_id", "uk_eligible"])
    op.create_index("ix_job_location_status", "jobs", ["location_verification_status"])


def downgrade() -> None:
    op.drop_index("ix_job_location_status", table_name="jobs")
    op.drop_index("ix_job_uk_eligible", table_name="jobs")
    with op.batch_alter_table("jobs") as batch:
        for column in reversed(_COLUMNS):
            batch.drop_column(column.name)
