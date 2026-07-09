"""threads_type

Revision ID: b1c2d3e4f5a6
Revises: fa2380eddbbb
Create Date: 2026-07-09 08:08:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'fa2380eddbbb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('threads', sa.Column('type', sa.String(length=20), server_default='chat', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('threads', 'type')
