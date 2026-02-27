"""split_name_into_first_last

Revision ID: 1f8b43fa65e8
Revises: fab1d2508a07
Create Date: 2026-02-27 00:32:58.407105

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1f8b43fa65e8'
down_revision: Union[str, None] = 'fab1d2508a07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add columns as nullable so existing rows are valid
    op.add_column('users', sa.Column('first_name', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('last_name', sa.String(length=100), nullable=True))

    # 2. Populate from name: first word → first_name, remainder → last_name (NULL if empty)
    op.execute("""
        UPDATE users
        SET first_name = split_part(name, ' ', 1),
            last_name  = NULLIF(trim(substring(name from position(' ' in name))), '')
    """)

    # 3. Tighten first_name to NOT NULL now that every row has a value
    op.alter_column('users', 'first_name', nullable=False)

    # 4. Drop the old column
    op.drop_column('users', 'name')


def downgrade() -> None:
    # 1. Add name back as nullable
    op.add_column('users', sa.Column('name', sa.VARCHAR(length=100), autoincrement=False, nullable=True))

    # 2. Reconstruct name from first_name + last_name
    op.execute("""
        UPDATE users
        SET name = CASE
            WHEN last_name IS NOT NULL AND last_name <> '' THEN first_name || ' ' || last_name
            ELSE first_name
        END
    """)

    # 3. Make name NOT NULL
    op.alter_column('users', 'name', nullable=False)

    # 4. Drop new columns
    op.drop_column('users', 'last_name')
    op.drop_column('users', 'first_name')
