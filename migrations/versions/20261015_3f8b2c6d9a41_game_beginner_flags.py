"""games beginner0/beginner1 flags

Revision ID: 3f8b2c6d9a41
Revises: 7c3a9e1d4f02
Create Date: 2026-10-15 17:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f8b2c6d9a41'
down_revision: Union[str, None] = '7c3a9e1d4f02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable without a default: a metadata-only change, no table rewrite
    op.add_column('games', sa.Column('beginner0', sa.Boolean(), nullable=True))
    op.add_column('games', sa.Column('beginner1', sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column('games', 'beginner1')
    op.drop_column('games', 'beginner0')
