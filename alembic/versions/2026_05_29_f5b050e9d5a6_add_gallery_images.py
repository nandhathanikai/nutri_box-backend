"""add_gallery_images

Revision ID: f5b050e9d5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-05-29 23:43:55.864351
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f5b050e9d5a6'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the gallery_images table
    op.create_table(
        'gallery_images',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('image_url', sa.String(length=500), nullable=False),
        sa.Column('caption', sa.String(length=255), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_gallery_images_id'), 'gallery_images', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_gallery_images_id'), table_name='gallery_images')
    op.drop_table('gallery_images')
