"""weibo social snapshots

Revision ID: 0a1b2c3d4e5f
Revises: f0a1b2c3d4e5
Create Date: 2026-08-06 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0a1b2c3d4e5f"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weibo_credentials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("cookies", sa.Text(), nullable=False),
        sa.Column("weibo_uid", sa.String(32), nullable=True),
        sa.Column("nickname", sa.String(128), nullable=True),
        sa.Column("avatar", sa.String(1024), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_weibo_credentials_user_id", "weibo_credentials", ["user_id"])

    op.create_table(
        "weibo_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("uid", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("avatar", sa.String(1024), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("profile_url", sa.String(1024), nullable=False),
        sa.Column("container_id", sa.String(128), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(16), nullable=False),
        sa.Column("last_sync_error", sa.String(1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid", name="uq_weibo_accounts_uid"),
    )

    op.create_table(
        "weibo_posts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("bid", sa.String(128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("media", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["weibo_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "external_id", name="uq_weibo_account_external"),
    )
    op.create_index("ix_weibo_posts_account_id", "weibo_posts", ["account_id"])
    op.create_index("ix_weibo_posts_published_at", "weibo_posts", ["published_at"])

    op.create_table(
        "weibo_subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["weibo_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "account_id", name="uq_weibo_sub_user_account"),
    )
    op.create_index("ix_weibo_subscriptions_user_id", "weibo_subscriptions", ["user_id"])


def downgrade() -> None:
    op.drop_table("weibo_subscriptions")
    op.drop_table("weibo_posts")
    op.drop_table("weibo_accounts")
    op.drop_table("weibo_credentials")
