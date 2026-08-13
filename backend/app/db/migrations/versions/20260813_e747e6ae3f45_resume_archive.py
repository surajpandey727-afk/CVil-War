"""resume_archive

Adds ``resumes.archived_at``.

A CV that has been sent to an employer cannot be hard-deleted: the FK is ``ON DELETE SET
NULL``, so removing the row would silently blank ``applications.resume_id`` and destroy the
record of what the employer actually received. Archiving hides it from the list and every
picker while leaving that reference intact.

Autogenerate also proposed dropping the ``server_default`` from seven columns on
``applications`` and ``platform_sessions``. Those are not drift: migration 0008 added them
deliberately so it could add NOT NULL columns to a populated table, and SQLite has no way to
express "default only during backfill". Dropping them here would rebuild ``applications``
through ``batch_alter_table`` — which recreates the table and its indexes, including the
partial unique ``uq_app_active_job`` — for no behavioural gain. They are left alone.

Revision ID: e747e6ae3f45
Revises: 08b65de44e8a
Create Date: 2026-08-13 18:52:24.813428+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e747e6ae3f45'
down_revision: Union[str, None] = '08b65de44e8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, so no server_default is needed and no table rebuild is triggered.
    op.add_column('resumes', sa.Column('archived_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('resumes', 'archived_at')
