"""app_versions singleton table

Revision ID: 7c3a9e1d4f02
Revises: 51d5c69f5a8e
Create Date: 2026-08-25 13:10:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c3a9e1d4f02'
down_revision: Union[str, None] = '51d5c69f5a8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'app_versions',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('min_supported_version', sa.String(length=20), nullable=False),
        sa.Column('latest_version', sa.String(length=20), nullable=False),
        sa.Column('update_message', sa.Text(), nullable=True),
        sa.Column('ios_min_supported_version', sa.String(length=20), nullable=True),
        sa.Column('android_min_supported_version', sa.String(length=20), nullable=True),
        sa.Column('ios_latest_version', sa.String(length=20), nullable=True),
        sa.Column('android_latest_version', sa.String(length=20), nullable=True),
        sa.Column('api_url', sa.String(length=256), nullable=True),
        sa.Column('moves_url', sa.String(length=256), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('app_versions')

