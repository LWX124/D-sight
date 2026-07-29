"""deep_analysis_credits

Revision ID: e9f0a1b2c3d4
Revises: c2d3e4f5a6b7
Create Date: 2026-07-29 12:00:00.000000

为 credit_transactions 增加 operation 列（reserve/settle/release）和
deep_analysis 计费幂等唯一索引，满足设计文档第 10.3 节账务不变量。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e9f0a1b2c3d4'
down_revision: Union[str, Sequence[str], None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # operation 列：reserve / settle / release，nullable 因为历史流水无此字段。
    op.add_column(
        'credit_transactions',
        sa.Column('operation', sa.String(length=16), nullable=True),
    )
    # 每个 deep_analysis 报告只能有一次 reserve / settle / release。
    op.create_index(
        'uq_credit_tx_deep_analysis',
        'credit_transactions',
        ['ref_type', 'ref_id', 'operation'],
        unique=True,
        postgresql_where=sa.text("ref_type = 'deep_analysis'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_credit_tx_deep_analysis', table_name='credit_transactions')
    op.drop_column('credit_transactions', 'operation')
