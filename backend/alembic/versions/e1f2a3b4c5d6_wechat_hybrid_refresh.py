"""Add canonical social identities and hard provider budgets.

Revision ID: e1f2a3b4c5d6
Revises: diagnosis_001
Create Date: 2026-08-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "diagnosis_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "social_publishers",
        sa.Column("sync_state", sa.String(length=32), server_default="queued", nullable=False),
    )
    op.add_column(
        "social_publishers", sa.Column("sync_provider", sa.String(length=32))
    )
    op.add_column(
        "social_publishers", sa.Column("last_sync_error_code", sa.String(length=64))
    )
    op.add_column(
        "social_publishers", sa.Column("next_sync_at", sa.DateTime(timezone=True))
    )

    op.create_table(
        "social_publisher_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("publisher_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("next_due_at", sa.DateTime(timezone=True)),
        sa.Column("requested_at", sa.DateTime(timezone=True)),
        sa.Column("waiting_since_at", sa.DateTime(timezone=True)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(length=64)),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active','coverage_gap','waiting_capacity',"
            "'identity_unresolved','identity_ambiguous','disabled')",
            name="ck_social_identity_status",
        ),
        sa.ForeignKeyConstraint(
            ["publisher_id"], ["social_publishers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "platform",
            "external_id",
            name="uq_social_identity_provider_platform_external",
        ),
    )
    op.create_index(
        "ix_social_identity_publisher", "social_publisher_identities", ["publisher_id"]
    )
    op.create_index(
        "ix_social_identity_due",
        "social_publisher_identities",
        ["status", "next_due_at"],
    )
    op.create_index(
        "ix_social_identity_waiting",
        "social_publisher_identities",
        ["status", "waiting_since_at"],
    )

    op.create_table(
        "social_provider_daily_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("request_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "request_count >= 0", name="ck_social_provider_daily_usage_nonnegative"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "usage_date", name="uq_social_provider_daily_usage"
        ),
    )
    op.create_index(
        "ix_social_provider_daily_usage_date",
        "social_provider_daily_usage",
        ["usage_date"],
    )

    # Backfill only explicit existing identities. Names are never used to merge.
    op.execute(
        """
        INSERT INTO social_publisher_identities
            (id, publisher_id, platform, provider, external_id, status,
             next_due_at, created_at, updated_at)
        SELECT gen_random_uuid(), id, platform,
               COALESCE(NULLIF(provider, ''),
                        CASE WHEN platform = 'weibo' THEN 'weibo' ELSE 'redfox' END),
               external_id, 'active', now(), now(), now()
        FROM social_publishers
        ON CONFLICT (provider, platform, external_id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE social_publishers
        SET sync_state = CASE
                WHEN last_sync_status = 'ok' THEN 'ok'
                WHEN last_sync_status IS NULL THEN 'queued'
                ELSE 'upstream_error'
            END,
            sync_provider = COALESCE(NULLIF(provider, ''),
                CASE WHEN platform = 'weibo' THEN 'weibo' ELSE NULL END),
            last_sync_error_code = CASE
                WHEN last_sync_status IS NOT NULL AND last_sync_status <> 'ok'
                THEN 'legacy_error' ELSE NULL END,
            next_sync_at = now()
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_social_provider_daily_usage_date",
        table_name="social_provider_daily_usage",
    )
    op.drop_table("social_provider_daily_usage")
    op.drop_index("ix_social_identity_waiting", table_name="social_publisher_identities")
    op.drop_index("ix_social_identity_due", table_name="social_publisher_identities")
    op.drop_index("ix_social_identity_publisher", table_name="social_publisher_identities")
    op.drop_table("social_publisher_identities")
    op.drop_column("social_publishers", "next_sync_at")
    op.drop_column("social_publishers", "last_sync_error_code")
    op.drop_column("social_publishers", "sync_provider")
    op.drop_column("social_publishers", "sync_state")
