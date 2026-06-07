"""add performance indexes

Revision ID: 2026_06_06_performance_indexes
Revises: 2026_06_05_delivery_mgmt
Create Date: 2026-06-06

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2026_06_06_performance_indexes'
down_revision = '2026_06_05_delivery_mgmt'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Subscriptions indexes
    op.create_index('ix_subscriptions_start_date', 'subscriptions', ['start_date'])
    op.create_index('ix_subscriptions_end_date', 'subscriptions', ['end_date'])

    # Delivery Cancellations indexes
    op.create_index('ix_delivery_cancellations_user_id', 'delivery_cancellations', ['user_id'])
    op.create_index('ix_delivery_cancellations_subscription_id', 'delivery_cancellations', ['subscription_id'])
    op.create_index('ix_delivery_cancellations_delivery_date', 'delivery_cancellations', ['delivery_date'])

    # Credits indexes
    op.create_index('ix_credits_user_id', 'credits', ['user_id'])
    op.create_index('ix_credits_subscription_id', 'credits', ['subscription_id'])
    op.create_index('ix_credits_cancellation_id', 'credits', ['cancellation_id'])


def downgrade() -> None:
    op.drop_index('ix_credits_cancellation_id', 'credits')
    op.drop_index('ix_credits_subscription_id', 'credits')
    op.drop_index('ix_credits_user_id', 'credits')
    op.drop_index('ix_delivery_cancellations_delivery_date', 'delivery_cancellations')
    op.drop_index('ix_delivery_cancellations_subscription_id', 'delivery_cancellations')
    op.drop_index('ix_delivery_cancellations_user_id', 'delivery_cancellations')
    op.drop_index('ix_subscriptions_end_date', 'subscriptions')
    op.drop_index('ix_subscriptions_start_date', 'subscriptions')
