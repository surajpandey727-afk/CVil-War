"""automation_and_role_targets

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-13 10:00:00.000000+00:00

Adds ``user_settings.role_targets`` and ``user_settings.automation``.

Both are nullable JSON. Nullable rather than defaulted so an existing row is not silently
given a policy the operator never chose — ``SettingsResponse`` coerces NULL to the schema
defaults on read, which keeps the API contract non-null without writing to anyone's row.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("role_targets", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("automation", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.drop_column("automation")
        batch_op.drop_column("role_targets")
