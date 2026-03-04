"""audit_log action enum to string

Revision ID: a1c7e3f49b02
Revises: be2a24c4faa8
Create Date: 2026-03-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c7e3f49b02'
down_revision: str = 'fd18e786a5a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'audit_logs',
        'action',
        type_=sa.String(50),
        existing_type=sa.Enum(
            'create', 'update', 'delete', 'login', 'export',
            name='audit_action_enum',
        ),
        postgresql_using='action::text',
    )
    op.execute("DROP TYPE IF EXISTS audit_action_enum")


def downgrade() -> None:
    audit_enum = sa.Enum(
        'create', 'update', 'delete', 'login', 'export',
        name='audit_action_enum',
    )
    audit_enum.create(op.get_bind(), checkfirst=True)
    op.alter_column(
        'audit_logs',
        'action',
        type_=audit_enum,
        existing_type=sa.String(50),
        postgresql_using='action::audit_action_enum',
    )
