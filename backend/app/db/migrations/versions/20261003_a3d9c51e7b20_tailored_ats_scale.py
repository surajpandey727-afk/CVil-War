"""Store tailored résumés' ATS score on the 0-1 scale every other record uses.

``generate_tailored_resume`` wrote the engine's 0-100 total straight into ``ats_score`` while
the rest of the product stores 0-1 and the UI multiplies by 100, so a tailored CV scoring 75
displayed as 7500. New records are written correctly; this rescales the ones already stored.
Values at or below 1 are already on the right scale and are left alone, so the migration is
safe to run twice.

Revision ID: a3d9c51e7b20
Revises: 7c41a9d3e2b8
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3d9c51e7b20"
down_revision: str | None = "7c41a9d3e2b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE resumes SET ats_score = ats_score / 100.0 "
        "WHERE type = 'tailored' AND ats_score IS NOT NULL AND ats_score > 1"
    )


def downgrade() -> None:
    # The old values were wrong; restoring them would reintroduce the bug.
    pass
