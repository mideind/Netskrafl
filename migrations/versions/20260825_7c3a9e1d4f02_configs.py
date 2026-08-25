"""configs table for JSON configuration documents

Revision ID: 7c3a9e1d4f02
Revises: 51d5c69f5a8e
Create Date: 2026-08-25 13:10:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '7c3a9e1d4f02'
down_revision: Union[str, None] = '51d5c69f5a8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'configs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('doc', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('configs')

