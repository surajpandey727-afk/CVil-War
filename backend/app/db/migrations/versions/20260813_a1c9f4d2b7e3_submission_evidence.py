"""submission_evidence

Adds the columns that let an application prove what actually happened:

* ``applications.submission_method``  — automated / manual / email / simulated / none
* ``applications.confirmation_state`` — confirmed / unconfirmed / simulated / pending / failed
* ``applications.confirmation_detail``— what the agent reported, verbatim
* ``platform_sessions.account_label`` — safe, masked identification of the login used

Backfill: rows that already reached a submitted status predate this recording entirely, so
their confirmation state is set to ``unconfirmed`` rather than left at ``pending``. Neither
value is flattering, and that is deliberate — ``pending`` would claim a submission is still in
flight, and ``confirmed`` would claim corroboration that was never captured. ``submission_method``
stays ``none`` for those rows, which the UI renders as "Not recorded" rather than inventing a
method. See docs rule: never fake missing data for historical records.

Both new NOT NULL columns carry a server_default so the ALTER succeeds against a populated
table; SQLite refuses it otherwise.

Revision ID: a1c9f4d2b7e3
Revises: e747e6ae3f45
Create Date: 2026-08-13 21:05:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1c9f4d2b7e3'
down_revision: Union[str, None] = 'e747e6ae3f45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Statuses that mean something was sent, or attempted, before this migration existed.
_SUBMITTED = ("'applying'", "'applied'", "'interview'", "'rejected'", "'offer'")


def upgrade() -> None:
    op.add_column(
        'applications',
        sa.Column(
            'submission_method', sa.String(length=20), nullable=False, server_default='none'
        ),
    )
    op.add_column(
        'applications',
        sa.Column(
            'confirmation_state', sa.String(length=20), nullable=False, server_default='pending'
        ),
    )
    op.add_column(
        'applications', sa.Column('confirmation_detail', sa.String(length=500), nullable=True)
    )
    op.add_column(
        'platform_sessions', sa.Column('account_label', sa.String(length=120), nullable=True)
    )

    op.execute(
        "UPDATE applications SET confirmation_state = 'unconfirmed' "
        f"WHERE status IN ({', '.join(_SUBMITTED)})"
    )
    op.execute(
        "UPDATE applications SET confirmation_state = 'failed' WHERE status = 'failed'"
    )


def downgrade() -> None:
    op.drop_column('platform_sessions', 'account_label')
    op.drop_column('applications', 'confirmation_detail')
    op.drop_column('applications', 'confirmation_state')
    op.drop_column('applications', 'submission_method')
