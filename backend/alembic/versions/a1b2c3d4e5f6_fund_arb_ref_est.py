"""fund_arb: add ref_est_nav and ref_premium to fund_arb_daily

Revision ID: a1b2c3d4e5f6
Revises: e30485f629c0
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'e30485f629c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('fund_arb_daily', sa.Column('ref_est_nav', sa.Float(), nullable=True))
    op.add_column('fund_arb_daily', sa.Column('ref_premium', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('fund_arb_daily', 'ref_premium')
    op.drop_column('fund_arb_daily', 'ref_est_nav')
