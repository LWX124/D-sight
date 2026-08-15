"""Cross-layer regressions for diagnosis persistence and route boundaries."""

from pathlib import Path


from app.main import create_app

from ..models import DiagnosisFile, DiagnosisRun, DiagnosisRunStatus, DiagnosisVersion


def _foreign_key_targets(table) -> dict[str, tuple[str, str]]:
    targets = {}
    for constraint in table.foreign_key_constraints:
        local = tuple(column.name for column in constraint.columns)
        remote = tuple(element.target_fullname for element in constraint.elements)
        targets[",".join(local)] = (",".join(remote), constraint.ondelete)
    return targets


def test_mock_diagnosis_routes_remain_unmounted():
    paths = create_app().openapi()["paths"]

    assert not any("diagnosis" in path for path in paths)


def test_orm_foreign_keys_and_composite_ownership_contract():
    file_fks = _foreign_key_targets(DiagnosisFile.__table__)
    version_fks = _foreign_key_targets(DiagnosisVersion.__table__)
    run_fks = _foreign_key_targets(DiagnosisRun.__table__)

    assert file_fks["user_id"] == ("users.id", "CASCADE")
    assert file_fks["deleted_by"] == ("users.id", "SET NULL")
    assert file_fks["current_version_id,id"] == (
        "diagnosis_versions.id,diagnosis_versions.diagnosis_file_id",
        "SET NULL (current_version_id)",
    )
    assert version_fks["diagnosis_file_id"] == ("diagnosis_files.id", "CASCADE")
    assert version_fks["parent_version_id,diagnosis_file_id"] == (
        "diagnosis_versions.id,diagnosis_versions.diagnosis_file_id",
        "SET NULL (parent_version_id)",
    )
    assert run_fks["user_id,diagnosis_file_id"] == (
        "diagnosis_files.user_id,diagnosis_files.id",
        "CASCADE",
    )
    assert run_fks["diagnosis_version_id,diagnosis_file_id"] == (
        "diagnosis_versions.id,diagnosis_versions.diagnosis_file_id",
        "SET NULL (diagnosis_version_id)",
    )


def test_run_status_and_numeric_constraints_match_runtime_contract():
    constraint_names = {
        constraint.name for constraint in DiagnosisRun.__table__.constraints
    }

    assert DiagnosisRunStatus.retry_wait.value == "retry_wait"
    assert "ck_lease_version_positive" in constraint_names


def test_orm_and_migration_share_instrument_provenance_fields():
    migration = (
        Path(__file__).parents[3] / "alembic" / "versions" / "add_diagnosis_tables.py"
    ).read_text(encoding="utf-8")
    columns = DiagnosisFile.__table__.columns

    assert columns["instrument_exchange"].nullable is True
    for field in (
        "instrument_original_input",
        "instrument_normalization_method",
        "instrument_ambiguity_resolved",
        "instrument_candidates",
    ):
        assert field in columns
        assert f'"{field}"' in migration


def test_migration_is_direct_single_chain_without_duplicate_evidence_tables():
    migration_path = (
        Path(__file__).parents[3] / "alembic" / "versions" / "add_diagnosis_tables.py"
    )
    migration = migration_path.read_text(encoding="utf-8")
    obsolete_merge = migration_path.with_name(
        "diagnosis_002_clean_tables_add_constraints.py"
    )

    assert 'down_revision: str | None = "d4e5f6a7b8c9"' in migration
    assert not obsolete_merge.exists()
    assert "evidence_pack_records" not in migration
    assert "provider_attempt_records" not in migration
    assert "evidence_pack_id" not in migration
    assert "fk_diagnosis_file_current_version" in migration
    assert "ck_diagnosis_run_status" in migration
