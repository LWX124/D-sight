"""fund_arb: 新增 base_symbol 字段

Revision ID: c2d3e4f5a6b7
Revises: a2b3c4d5e6f7
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'c2d3e4f5a6b7'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('fund_arb_funds', sa.Column('base_symbol', sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column('fund_arb_funds', 'base_symbol')
