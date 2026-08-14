"""fit_analyses

Stores one job-vs-CV assessment per (user, job, resume). The full report is JSON; only
``overall`` and ``method`` are promoted to columns, because those are the two things a list
view needs without deserialising the payload.

Autogenerate additionally proposed changing ``applications.submission_method`` and
``confirmation_state`` from VARCHAR(20) to native enums. That is not drift: migration
a1c9f4d2b7e3 created them as VARCHAR deliberately so the ALTER would succeed on SQLite, and
``pg_enum`` already degrades to VARCHAR outside PostgreSQL. Applying it would rebuild
``applications`` through batch_alter_table — recreating the partial unique ``uq_app_active_job``
— for no behavioural gain. Left alone.

Revision ID: 0d60af14cb51
Revises: a1c9f4d2b7e3
Create Date: 2026-08-14 08:55:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0d60af14cb51'
down_revision: Union[str, None] = 'a1c9f4d2b7e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'fit_analyses',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('job_id', sa.String(length=32), nullable=False),
        # SET NULL, not CASCADE: deleting a CV must not erase the record that this job was
        # assessed. The payload still carries the CV's name as it was at the time.
        sa.Column('resume_id', sa.String(length=32), nullable=True),
        sa.Column('overall', sa.Float(), nullable=False, server_default='0'),
        sa.Column('method', sa.String(length=20), nullable=False, server_default='keyword'),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('analysed_at', sa.DateTime(), nullable=True),
        # server_default matters: TimestampMixin relies on the database supplying these, and
        # omitting it here made every insert fail on a NOT NULL violation.
        sa.Column('created_at', sa.DateTime(),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['resume_id'], ['resumes.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_fit_analyses_job_id', 'fit_analyses', ['job_id'])
    op.create_index('ix_fit_analyses_user_id', 'fit_analyses', ['user_id'])
    # One current answer per pair; a re-run replaces rather than accumulates.
    op.create_index(
        'uq_fit_job_resume', 'fit_analyses', ['user_id', 'job_id', 'resume_id'], unique=True
    )


def downgrade() -> None:
    op.drop_index('uq_fit_job_resume', table_name='fit_analyses')
    op.drop_index('ix_fit_analyses_user_id', table_name='fit_analyses')
    op.drop_index('ix_fit_analyses_job_id', table_name='fit_analyses')
    op.drop_table('fit_analyses')
