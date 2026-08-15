"""Add stock diagnosis persistence tables.

Revision ID: diagnosis_001
Revises: d4e5f6a7b8c9
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "diagnosis_001"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "diagnosis_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("instrument_canonical_symbol", sa.String(32), nullable=False),
        sa.Column("instrument_market", sa.String(4), nullable=False),
        sa.Column("instrument_exchange", sa.String(16)),
        sa.Column("instrument_display_name", sa.String(128)),
        sa.Column(
            "instrument_currency", sa.String(8), nullable=False, server_default="USD"
        ),
        sa.Column(
            "instrument_timezone", sa.String(32), nullable=False, server_default="UTC"
        ),
        sa.Column("instrument_original_input", sa.String(128)),
        sa.Column("instrument_normalization_method", sa.String(32)),
        sa.Column(
            "instrument_ambiguity_resolved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("instrument_candidates", postgresql.JSONB()),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("metadata_json", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "deleted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.UniqueConstraint("user_id", "id", name="uq_diagnosis_file_owner_id"),
        sa.CheckConstraint(
            "status IN ('active','archived','deleted')",
            name="ck_diagnosis_file_status",
        ),
    )
    op.create_index("ix_diagnosis_files_user_id", "diagnosis_files", ["user_id"])
    op.create_index(
        "uq_diagnosis_file_active",
        "diagnosis_files",
        ["user_id", "instrument_canonical_symbol"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_diagnosis_file_owner_history",
        "diagnosis_files",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_diagnosis_files_current_version_id",
        "diagnosis_files",
        ["current_version_id"],
    )

    op.create_table(
        "diagnosis_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "diagnosis_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("diagnosis_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("analysis_version", sa.String(64), nullable=False),
        sa.Column("decision_profile_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_pack", postgresql.JSONB(), nullable=False),
        sa.Column("dimension_opinions", postgresql.JSONB()),
        sa.Column("conflict_review", postgresql.JSONB()),
        sa.Column("risk_assessment", postgresql.JSONB()),
        sa.Column("diagnosis_advice", postgresql.JSONB()),
        sa.Column("provenance", postgresql.JSONB()),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(64), nullable=False, server_default="initial"),
        sa.Column("parent_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "id", "diagnosis_file_id", name="uq_diagnosis_version_id_file"
        ),
        sa.CheckConstraint(
            "version_number > 0", name="ck_version_number_positive"
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id", "diagnosis_file_id"],
            ["diagnosis_versions.id", "diagnosis_versions.diagnosis_file_id"],
            name="fk_diagnosis_version_parent_file",
            ondelete="SET NULL (parent_version_id)",
        ),
    )
    op.create_index(
        "ix_diagnosis_versions_diagnosis_file_id",
        "diagnosis_versions",
        ["diagnosis_file_id"],
    )
    op.create_index(
        "uq_diagnosis_version_number",
        "diagnosis_versions",
        ["diagnosis_file_id", "version_number"],
        unique=True,
    )
    op.create_index(
        "ix_diagnosis_version_fingerprint",
        "diagnosis_versions",
        ["analysis_version"],
    )

    op.create_foreign_key(
        "fk_diagnosis_file_current_version",
        "diagnosis_files",
        "diagnosis_versions",
        ["current_version_id", "id"],
        ["id", "diagnosis_file_id"],
        ondelete="SET NULL (current_version_id)",
    )

    op.create_table(
        "diagnosis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("diagnosis_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("diagnosis_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("stage", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("progress", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column(
            "attempt_count", sa.SmallInteger(), nullable=False, server_default="0"
        ),
        sa.Column("max_attempts", sa.SmallInteger(), nullable=False, server_default="3"),
        sa.Column("worker_id", sa.String(128)),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True)),
        sa.Column("lease_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column(
            "next_retry_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("instrument_data", postgresql.JSONB()),
        sa.Column("decision_profile", postgresql.JSONB()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "credit_state", sa.String(16), nullable=False, server_default="reserved"
        ),
        sa.Column("reserved_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("settled_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["user_id", "diagnosis_file_id"],
            ["diagnosis_files.user_id", "diagnosis_files.id"],
            name="fk_diagnosis_run_owner_file",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["diagnosis_version_id", "diagnosis_file_id"],
            ["diagnosis_versions.id", "diagnosis_versions.diagnosis_file_id"],
            name="fk_diagnosis_run_version_file",
            ondelete="SET NULL (diagnosis_version_id)",
        ),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_progress_range"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_attempt_count_positive"),
        sa.CheckConstraint("max_attempts > 0", name="ck_max_attempts_positive"),
        sa.CheckConstraint("lease_version >= 0", name="ck_lease_version_positive"),
        sa.CheckConstraint(
            "reserved_credits >= 0", name="ck_reserved_credits_positive"
        ),
        sa.CheckConstraint(
            "settled_credits >= 0", name="ck_settled_credits_positive"
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','retry_wait','completed','failed','cancelled')",
            name="ck_diagnosis_run_status",
        ),
        sa.CheckConstraint(
            "credit_state IN ('reserved','settled','released')",
            name="ck_diagnosis_run_credit_state",
        ),
    )
    op.create_index("ix_diagnosis_runs_user_id", "diagnosis_runs", ["user_id"])
    op.create_index(
        "ix_diagnosis_runs_diagnosis_file_id",
        "diagnosis_runs",
        ["diagnosis_file_id"],
    )
    op.create_index(
        "ix_diagnosis_runs_diagnosis_version_id",
        "diagnosis_runs",
        ["diagnosis_version_id"],
    )
    op.create_index(
        "ix_diagnosis_run_worker_claim",
        "diagnosis_runs",
        ["next_retry_at", "created_at"],
        postgresql_where=sa.text("status IN ('pending','retry_wait')"),
    )
    op.create_index(
        "ix_diagnosis_run_stale_running",
        "diagnosis_runs",
        ["heartbeat_at"],
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_table("diagnosis_runs")
    op.drop_constraint(
        "fk_diagnosis_file_current_version", "diagnosis_files", type_="foreignkey"
    )
    op.drop_table("diagnosis_versions")
    op.drop_table("diagnosis_files")
