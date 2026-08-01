"""thread_last_message_at

Revision ID: 4dfd3378d565
Revises: 7e2c0713f82d
Create Date: 2026-07-31 17:15:19.199864

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4dfd3378d565'
down_revision: Union[str, Sequence[str], None] = 'd8381ce6d30d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 添加字段，允许 NULL
    op.add_column('threads', sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True))

    # 数据迁移：将现有 threads 的 last_message_at 初始化为 updated_at
    op.execute("UPDATE threads SET last_message_at = updated_at WHERE last_message_at IS NULL")

    # 设置为非空约束，并为新会话提供数据库端 UTC 时间默认值
    op.alter_column(
        'threads',
        'last_message_at',
        nullable=False,
        server_default=sa.func.now(),
    )

    # 新增索引
    op.create_index(op.f('ix_threads_last_message_at'), 'threads', ['last_message_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_threads_last_message_at'), table_name='threads')
    op.drop_column('threads', 'last_message_at')
