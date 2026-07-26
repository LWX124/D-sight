"""fund_arb_reconciliation 复合索引替换独立索引

Revision ID: a2b3c4d5e6f7
Revises: f2a3b4c5d6e7
Create Date: 2026-07-24

"""
from alembic import op

revision = 'a2b3c4d5e6f7'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index('ix_fund_arb_reconciliation_fund_code', table_name='fund_arb_reconciliation')
    op.drop_index('ix_fund_arb_reconciliation_run_at', table_name='fund_arb_reconciliation')
    op.create_index(
        'ix_fund_arb_reconciliation_code_run_at',
        'fund_arb_reconciliation',
        ['fund_code', 'run_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_fund_arb_reconciliation_code_run_at', table_name='fund_arb_reconciliation')
    op.create_index('ix_fund_arb_reconciliation_fund_code', 'fund_arb_reconciliation', ['fund_code'])
    op.create_index('ix_fund_arb_reconciliation_run_at', 'fund_arb_reconciliation', ['run_at'])
