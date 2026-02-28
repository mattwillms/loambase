"""add budget_reached to seeder_status_enum

Revision ID: be2a24c4faa8
Revises: b0339d9470a9
Create Date: 2026-02-28 07:44:58.680584

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'be2a24c4faa8'
down_revision: Union[str, None] = 'b0339d9470a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE seeder_status_enum ADD VALUE IF NOT EXISTS 'budget_reached'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values
    pass
