"""add image_cache_failed to plants

Revision ID: a7f2e9d41b63
Revises: e1a3b5c7d9f0
Create Date: 2026-03-21
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7f2e9d41b63'
down_revision: Union[str, None] = 'e1a3b5c7d9f0'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column('plants', sa.Column('image_cache_failed', sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column('plants', sa.Column('image_cache_failed_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('plants', 'image_cache_failed_reason')
    op.drop_column('plants', 'image_cache_failed')
