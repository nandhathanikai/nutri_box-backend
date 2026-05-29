"""Add paid status to custom plan requests constraint

Revision ID: 5d7aa30835a6
Revises: 594d9547c1d5
Create Date: 2026-05-18 20:40:24.903984
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5d7aa30835a6'
down_revision: Union[str, None] = '594d9547c1d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the old constraint
    op.execute("ALTER TABLE custom_plan_requests DROP CONSTRAINT ck_custom_requests_status")
    # Add the new constraint including 'paid'
    op.execute("ALTER TABLE custom_plan_requests ADD CONSTRAINT ck_custom_requests_status CHECK (status IN ('pending', 'priced', 'accepted', 'rejected', 'paid'))")


def downgrade() -> None:
    # Drop the new constraint
    op.execute("ALTER TABLE custom_plan_requests DROP CONSTRAINT ck_custom_requests_status")
    # Revert to the old constraint
    op.execute("ALTER TABLE custom_plan_requests ADD CONSTRAINT ck_custom_requests_status CHECK (status IN ('pending', 'priced', 'accepted', 'rejected'))")
