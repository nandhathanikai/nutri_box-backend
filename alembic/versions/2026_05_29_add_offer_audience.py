"""Add audience column to offers table

Revision ID: a1b2c3d4e5f6
Revises: 5d7aa30835a6
Create Date: 2026-05-29 23:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '5d7aa30835a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add audience column with default 'all' — safe additive migration
    op.add_column(
        'offers',
        sa.Column('audience', sa.String(30), nullable=False, server_default='all')
    )


def downgrade() -> None:
    op.drop_column('offers', 'audience')
