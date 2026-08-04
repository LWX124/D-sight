"""thread_last_message_at server default

修复历史迁移 4dfd3378d565 被事后编辑导致的 schema drift：
早期应用该迁移的库上 threads.last_message_at 是 NOT NULL 但没有 DEFAULT，
而 ORM 模型依赖 server_default 提供值（INSERT 不带该列）→ NotNullViolation。
本迁移幂等地把 DEFAULT now() 补齐，让所有环境收敛。

Revision ID: f0a1b2c3d4e5
Revises: 7e2c0713f82d
Create Date: 2026-08-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f0a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = '7e2c0713f82d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 兜底：极端情况下存在遗留 NULL 行（曾用 nullable=True 阶段写入）
    op.execute("UPDATE threads SET last_message_at = updated_at WHERE last_message_at IS NULL")
    op.alter_column(
        'threads',
        'last_message_at',
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=sa.text('now()'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'threads',
        'last_message_at',
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=None,
    )
