"""AIHot data pipeline tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-11 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. hot_source_memberships
    op.create_table(
        "hot_source_memberships",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("publisher_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default=sa.text("'redfox'")),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False, server_default=sa.text("'market'")),
        sa.Column("source_key", sa.String(length=128), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("added_by", sa.UUID(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["publisher_id"], ["social_publishers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("publisher_id IS NOT NULL OR source_key IS NOT NULL", name="ck_hot_source_target"),
        sa.UniqueConstraint("publisher_id", name="uq_hot_source_publisher"),
        sa.UniqueConstraint("provider", "platform", "source_key", name="uq_hot_source_search_key"),
    )
    op.create_index("ix_hot_source_memberships_category", "hot_source_memberships", ["category"])
    op.create_index("ix_hot_source_memberships_enabled", "hot_source_memberships", ["enabled"])

    op.create_table(
        "hot_item_sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["social_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["hot_source_memberships.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "source_id", name="uq_hot_item_source"),
    )
    op.create_index("ix_hot_item_sources_source_discovered", "hot_item_sources", ["source_id", sa.text("discovered_at DESC")])

    # 2. hot_runs
    op.create_table(
        "hot_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default=sa.text("'redfox'")),
        sa.Column("source_key", sa.String(length=128), nullable=True),
        sa.Column("run_type", sa.String(length=16), nullable=False, server_default=sa.text("'scheduled'")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("items_fetched", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("items_new", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("items_updated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("formula_version", sa.String(length=32), nullable=False, server_default=sa.text("'v1'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hot_runs_status_finished", "hot_runs", ["status", sa.text("finished_at DESC")])

    # 3. hot_rankings
    op.create_table(
        "hot_rankings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("window", sa.String(length=8), nullable=False),
        sa.Column("aihot_score", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("previous_rank", sa.Integer(), nullable=True),
        sa.Column("rank_delta", sa.Integer(), nullable=True),
        sa.Column("platform_score", sa.Float(), nullable=False),
        sa.Column("freshness_score", sa.Float(), nullable=False),
        sa.Column("momentum_score", sa.Float(), nullable=False),
        sa.Column("formula_version", sa.String(length=32), nullable=False, server_default=sa.text("'v1'")),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["hot_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["social_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "item_id", "window", name="uq_hot_ranking_run_item_window"),
    )
    op.create_index(
        "ix_hot_rankings_run_window_category_rank",
        "hot_rankings",
        ["run_id", "window", "category", "rank"],
    )
    op.create_index("ix_hot_rankings_computed_at", "hot_rankings", ["computed_at"])

    # 4. provider_call_logs
    op.create_table(
        "provider_call_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("endpoint", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("response_size", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("estimated_cost", sa.Numeric(10, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_provider_call_logs_created_at", "provider_call_logs", ["created_at"])
    op.create_index(
        "ix_provider_call_logs_provider_operation_created",
        "provider_call_logs",
        ["provider", "operation", sa.text("created_at DESC")],
    )

    # 5. content_enrichments
    op.create_table(
        "content_enrichments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("is_financial", sa.Boolean(), nullable=True),
        sa.Column("relevance_confidence", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("assets", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["social_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "version", name="uq_content_enrichment_item_version"),
    )
    op.create_index("ix_content_enrichments_category", "content_enrichments", ["category"])

    # 6. raw provider responses, automatically expired by the daily cleanup job.
    op.create_table(
        "provider_raw_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_provider_raw_records_expires_at", "provider_raw_records", ["expires_at"])


def downgrade() -> None:
    op.drop_table("provider_raw_records")
    op.drop_table("content_enrichments")
    op.drop_table("provider_call_logs")
    op.drop_table("hot_rankings")
    op.drop_table("hot_runs")
    op.drop_table("hot_item_sources")
    op.drop_table("hot_source_memberships")
