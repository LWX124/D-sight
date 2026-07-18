"""wechat article title -> text

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-07-15 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 公众号「文字消息」无标题，接口把全文塞进 title，可远超 512 字符
    op.alter_column("wechat_articles", "title", type_=sa.Text(), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("wechat_articles", "title", type_=sa.String(length=512), existing_nullable=False)
