"""make planting bed_id nullable, add garden_id

Revision ID: e1a3b5c7d9f0
Revises: c484a79139c2
Create Date: 2026-03-06
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1a3b5c7d9f0'
down_revision: Union[str, None] = 'c484a79139c2'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.alter_column('plantings', 'bed_id', existing_type=sa.Integer(), nullable=True)
    op.add_column('plantings', sa.Column('garden_id', sa.Integer(), sa.ForeignKey('gardens.id', ondelete='CASCADE'), nullable=True))
    op.create_index('ix_plantings_garden_id', 'plantings', ['garden_id'])


def downgrade() -> None:
    op.drop_index('ix_plantings_garden_id', 'plantings')
    op.drop_column('plantings', 'garden_id')
    op.alter_column('plantings', 'bed_id', existing_type=sa.Integer(), nullable=False)
