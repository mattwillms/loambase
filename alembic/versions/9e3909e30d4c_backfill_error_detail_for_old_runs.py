"""backfill error_detail for old runs

Revision ID: 9e3909e30d4c
Revises: be2a24c4faa8
Create Date: 2026-02-28 08:13:51.743791

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9e3909e30d4c"
down_revision: Union[str, None] = "be2a24c4faa8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE data_source_runs "
        "SET error_detail = 'Error details not captured (pre-fix run)' "
        "WHERE errors > 0 AND error_detail IS NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE data_source_runs "
        "SET error_detail = NULL "
        "WHERE error_detail = 'Error details not captured (pre-fix run)'"
    )
