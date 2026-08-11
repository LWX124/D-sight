"""unified social tables

Revision ID: b2c3d4e5f6a7
Revises: 0a1b2c3d4e5f
Create Date: 2026-08-11 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "0a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # 1. social_publishers
    op.create_table(
        "social_publishers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("avatar", sa.String(length=1024), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("profile_url", sa.String(length=1024), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("provider_ref", sa.String(length=256), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=16), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column(
            "platform_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "external_id", name="uq_social_publishers_platform_ext"),
    )
    op.create_index("ix_social_publishers_platform", "social_publishers", ["platform"])
    op.create_index(
        "ix_social_publishers_name_trgm",
        "social_publishers",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )

    # 2. social_items
    op.create_table(
        "social_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("publisher_id", sa.UUID(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("content_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("transcript_text", sa.Text(), nullable=True),
        sa.Column("digest", sa.String(length=2048), nullable=True),
        sa.Column("cover_url", sa.String(length=1024), nullable=True),
        sa.Column("url", sa.String(length=1024), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("body_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("body_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("enrichment_status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column(
            "platform_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["publisher_id"], ["social_publishers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "external_id", name="uq_social_items_platform_ext"),
    )
    op.create_index("ix_social_items_publisher_id", "social_items", ["publisher_id"])
    op.create_index("ix_social_items_published_at", "social_items", ["published_at"])
    op.create_index("ix_social_items_content_hash", "social_items", ["content_hash"])
    op.create_index(
        "ix_social_items_body_expires_at", "social_items", ["body_expires_at"]
    )
    op.create_index(
        "ix_social_items_title_trgm",
        "social_items",
        ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_social_items_digest_trgm",
        "social_items",
        ["digest"],
        postgresql_using="gin",
        postgresql_ops={"digest": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_social_items_publisher_feed",
        "social_items",
        ["publisher_id", sa.text("published_at DESC"), sa.text("id DESC")],
    )

    # 3. social_item_metric_snapshots
    op.create_table(
        "social_item_metric_snapshots",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=True),
        sa.Column("share_count", sa.Integer(), nullable=True),
        sa.Column("collect_count", sa.Integer(), nullable=True),
        sa.Column("provider_rank", sa.Integer(), nullable=True),
        sa.Column(
            "raw_metrics",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["item_id"], ["social_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "captured_at", name="uq_social_metrics_item_captured"),
    )
    op.create_index("ix_social_metrics_item_captured", "social_item_metric_snapshots", ["item_id", "captured_at"])

    # 4. social_subscriptions
    op.create_table(
        "social_subscriptions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("publisher_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["publisher_id"], ["social_publishers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "publisher_id", name="uq_social_sub_user_publisher"),
    )
    op.create_index("ix_social_subscriptions_user_id", "social_subscriptions", ["user_id"])
    op.create_index(
        "ix_social_subscriptions_user_enabled_publisher",
        "social_subscriptions",
        ["user_id", "enabled", "publisher_id"],
    )

    # 5. social_item_media
    op.create_table(
        "social_item_media",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("thumbnail_url", sa.String(length=1024), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["social_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_social_media_item_id", "social_item_media", ["item_id"])


def downgrade() -> None:
    op.drop_table("social_item_media")
    op.drop_table("social_subscriptions")
    op.drop_table("social_item_metric_snapshots")
    op.drop_table("social_items")
    op.drop_table("social_publishers")
