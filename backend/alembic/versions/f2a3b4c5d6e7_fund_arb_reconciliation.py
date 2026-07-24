"""fund_arb: add fund_arb_reconciliation table

Revision ID: f2a3b4c5d6e7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'f2a3b4c5d6e7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'fund_arb_reconciliation',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('fund_code', sa.String(length=16), nullable=False),
        sa.Column('run_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('local_est_nav', sa.Float(), nullable=False),
        sa.Column('ref_est_nav', sa.Float(), nullable=False),
        sa.Column('deviation_pct', sa.Float(), nullable=False),
        sa.Column('threshold_used', sa.Float(), nullable=False),
        sa.Column('action', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_fund_arb_reconciliation_fund_code'), 'fund_arb_reconciliation', ['fund_code'], unique=False)
    op.create_index(op.f('ix_fund_arb_reconciliation_run_at'), 'fund_arb_reconciliation', ['run_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_fund_arb_reconciliation_run_at'), table_name='fund_arb_reconciliation')
    op.drop_index(op.f('ix_fund_arb_reconciliation_fund_code'), table_name='fund_arb_reconciliation')
    op.drop_table('fund_arb_reconciliation')
