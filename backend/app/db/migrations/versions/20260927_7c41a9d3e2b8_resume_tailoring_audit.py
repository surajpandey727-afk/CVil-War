"""Record what a tailoring pass changed, on the résumé it produced.

A tailored CV the operator cannot interrogate is one they have to take on trust, and the
engine that produced the previous generation of these documents had earned none. The audit
holds the before and after score with its components, every bullet that changed with the
evidence that justified it, every edit that was rejected and why, and the keywords the CV
could not support — so the question "what did you change and why" has an answer attached to
the artefact rather than living in a log line.

Revision ID: 7c41a9d3e2b8
Revises: 004bc1688569
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c41a9d3e2b8"
down_revision: str | None = "004bc1688569"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable with no default: "generated before auditing existed" and "audited and found
    # nothing to change" are different facts, and a default of {} would conflate them.
    op.add_column("resumes", sa.Column("tailoring_audit", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("resumes", "tailoring_audit")
