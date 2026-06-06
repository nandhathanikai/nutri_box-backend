"""add delivery management tables and user location fields

Revision ID: 2026_06_05_delivery_mgmt
Revises: 2026_05_29_f5b050e9d5a6_add_gallery_images
Create Date: 2026-06-05

Changes:
  - users: add latitude, longitude (float), is_active (bool default True)
  - New table: delivery_sessions
  - New table: delivery_assignments
  - New table: delivery_tracking
  - New table: driver_status
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '2026_06_05_delivery_mgmt'
down_revision = 'f5b050e9d5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Extend users table ─────────────────────────────────────────────────
    op.add_column('users', sa.Column('latitude', sa.Float(), nullable=True))
    op.add_column('users', sa.Column('longitude', sa.Float(), nullable=True))
    op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'))

    # ── 2. delivery_sessions ──────────────────────────────────────────────────
    op.create_table(
        'delivery_sessions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(50), nullable=False, unique=True),
        sa.Column('slug', sa.String(50), nullable=False, unique=True),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Seed default sessions so existing BF/DINNER orders still work
    op.execute("""
        INSERT INTO delivery_sessions (name, slug, display_order, is_active)
        VALUES
            ('Breakfast', 'breakfast', 1, true),
            ('Lunch',     'lunch',     2, true),
            ('Dinner',    'dinner',    3, true)
        ON CONFLICT (slug) DO NOTHING;
    """)

    # ── 3. delivery_assignments ───────────────────────────────────────────────
    op.create_table(
        'delivery_assignments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('subscription_id', sa.Integer(), sa.ForeignKey('subscriptions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('driver_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('delivery_sessions.id'), nullable=False),
        sa.Column('delivery_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='assigned'),
        sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_delivery_assignments_driver_date', 'delivery_assignments', ['driver_id', 'delivery_date'])
    op.create_index('ix_delivery_assignments_customer', 'delivery_assignments', ['customer_id'])
    op.create_unique_constraint(
        'uq_assignment_sub_date_session',
        'delivery_assignments',
        ['subscription_id', 'delivery_date', 'session_id']
    )

    # ── 4. delivery_tracking ──────────────────────────────────────────────────
    op.create_table(
        'delivery_tracking',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('assignment_id', sa.Integer(), sa.ForeignKey('delivery_assignments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('driver_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_delivery_tracking_assignment', 'delivery_tracking', ['assignment_id'])

    # ── 5. driver_status ──────────────────────────────────────────────────────
    op.create_table(
        'driver_status',
        sa.Column('driver_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='offline'),
        sa.Column('current_session_id', sa.Integer(), sa.ForeignKey('delivery_sessions.id'), nullable=True),
        sa.Column('current_assignment_id', sa.Integer(), sa.ForeignKey('delivery_assignments.id', ondelete='SET NULL'), nullable=True),
        sa.Column('last_latitude', sa.Float(), nullable=True),
        sa.Column('last_longitude', sa.Float(), nullable=True),
        sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('driver_status')
    op.drop_table('delivery_tracking')
    op.drop_constraint('uq_assignment_sub_date_session', 'delivery_assignments', type_='unique')
    op.drop_index('ix_delivery_assignments_driver_date', 'delivery_assignments')
    op.drop_index('ix_delivery_assignments_customer', 'delivery_assignments')
    op.drop_table('delivery_assignments')
    op.drop_table('delivery_sessions')
    op.drop_column('users', 'is_active')
    op.drop_column('users', 'longitude')
    op.drop_column('users', 'latitude')
