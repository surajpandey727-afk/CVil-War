"""add 'resume_intelligence_tailor' and 'ats_review' to llm_purpose enum

Revision ID: 004bc1688569
Revises: 222bb0d3cd7e
Create Date: 2026-09-20 00:00:00.000000+00:00

Two call sites pass a ``purpose`` string that was never added to the native ``llm_purpose``
enum, so any *successful* (non-degraded) LLM call through them fails when
``LLMClient._persist_usage`` tries to INSERT the usage row:

- ``resume_tailoring.tailor_job`` passes ``"resume_intelligence_tailor"`` (Resume
  Intelligence's job-tailoring analysis — distinct from the older document generator's
  ``"resume_tailor"``, which stays as-is).
- ``resume.review_resume_with_llm`` passes ``"ats_review"`` (the on-demand deep ATS review,
  distinct from ``"ats_optimize"``, the resume-rewrite pass).

Same fix pattern as 0004 (adding 'general').
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004bc1688569"
down_revision: Union[str, None] = "222bb0d3cd7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # PG 12+ permits ADD VALUE inside a transaction; idempotent on partial state.
        op.execute("ALTER TYPE llm_purpose ADD VALUE IF NOT EXISTS 'resume_intelligence_tailor'")
        op.execute("ALTER TYPE llm_purpose ADD VALUE IF NOT EXISTS 'ats_review'")


def downgrade() -> None:
    # Removing a value from a PostgreSQL enum that may be in use is unsupported; no-op.
    pass
