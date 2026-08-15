"""Regression tests for structured stock-skill capability auditing."""

from pathlib import Path

from ..audit.skill_audit import audit_skill, discover_stock_skills, parse_skill_md


def _write_skill(root: Path, name: str, frontmatter: str, body: str = "") -> Path:
    skill_dir = root / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\n{frontmatter}\n---\n{body}", encoding="utf-8"
    )
    return skill_dir


def test_missing_required_tool_makes_skill_unavailable(tmp_path):
    skill_dir = _write_skill(
        tmp_path,
        "stock-check",
        "quantSkills:\n  tags: [stock]\n",
        "Run `tools/check.py --strict symbol`.",
    )

    capability = audit_skill(skill_dir)

    assert capability.status == "unavailable"
    assert [dependency.path for dependency in capability.missing_dependencies] == [
        "tools/check.py"
    ]


def test_only_optional_or_degradable_gaps_make_skill_degraded(tmp_path):
    skill_dir = _write_skill(
        tmp_path,
        "stock-check",
        "quantSkills:\n"
        "  tags: [stock]\n"
        "  requires:\n"
        "    - id: optional-feed\n"
        "      required: false\n"
        "    - id: fallback-feed\n"
        "      required: true\n"
        "      degraded_capable: true\n",
    )

    capability = audit_skill(skill_dir)

    assert capability.status == "degraded"
    assert {dependency.path for dependency in capability.missing_dependencies} == {
        "optional-feed",
        "fallback-feed",
    }


def test_command_paths_are_normalized_and_deduplicated(tmp_path):
    skill_dir = _write_skill(
        tmp_path,
        "stock-check",
        "quantSkills:\n  tags: [stock]\n",
        "Run `python3 scripts/check.py --strict input.json`, then "
        "`scripts/check.py input.json`; read `references/guide.md#usage`.",
    )
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "check.py").write_text("", encoding="utf-8")
    (skill_dir / "references").mkdir()
    (skill_dir / "references" / "guide.md").write_text("", encoding="utf-8")

    parsed = parse_skill_md(skill_dir / "SKILL.md")
    capability = audit_skill(skill_dir)

    assert [dependency.path for dependency in parsed["dependencies"]] == [
        "references/guide.md",
        "scripts/check.py",
    ]
    # 本用例只验证路径归一化与去重。状态是 unavailable：这两个文件在仓库里存在，
    # 但 skill 目录内的文件不会写入工作区，见 test_skill_local_files_are_unreachable_even_when_present。
    assert capability.status == "unavailable"


def test_body_reference_does_not_override_structured_optional_semantics(tmp_path):
    skill_dir = _write_skill(
        tmp_path,
        "stock-check",
        "quantSkills:\n"
        "  tags: [stock]\n"
        "  requires:\n"
        "    - path: tools/optional.py\n"
        "      kind: tool\n"
        "      required: false\n",
        "Optionally run `python tools/optional.py --verbose`.",
    )

    capability = audit_skill(skill_dir)

    assert capability.status == "degraded"
    assert capability.missing_dependencies[0].required is False


def test_structured_tags_override_keyword_fallback(tmp_path):
    tagged_non_stock = _write_skill(
        tmp_path,
        "generic-research",
        "quantSkills:\n  tags: [writing]\n",
        "This body mentions stock portfolios.",
    )
    fallback_stock = _write_skill(
        tmp_path,
        "legacy-stock",
        "description: Analyze a stock portfolio",
    )

    discovered = discover_stock_skills(tmp_path)

    assert tagged_non_stock not in discovered
    assert fallback_stock in discovered


def test_capability_serialization_is_stable(tmp_path):
    skill_dir = _write_skill(
        tmp_path,
        "stock-check",
        "quantSkills:\n  tags: [stock]\n",
    )

    payload = audit_skill(skill_dir).to_dict()

    assert payload == {
        "skill_id": "stock-check",
        "status": "runnable",
        "dependencies": [],
        "materialized_dependencies": [],
        "missing_dependencies": [],
        "last_verified": None,
        "notes": None,
    }


def test_shared_tools_directory_counts_as_reachable(tmp_path):
    """`tools/` 是全量拷进工作区的共享目录，按 skill 目录去找会把可用的判成缺失。"""
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "financial_rigor.py").write_text("", encoding="utf-8")
    skill_dir = _write_skill(
        skills_root,
        "stock-check",
        "quantSkills:\n  tags: [stock]\n",
        "Run `python3 tools/financial_rigor.py 600519`.",
    )

    capability = audit_skill(skill_dir)

    assert capability.status == "runnable"
    assert capability.missing_dependencies == []


def test_skill_local_files_are_unreachable_even_when_present(tmp_path):
    """materialize 只写 SKILL.md：skill 目录里的 references/ 就算在仓库里也进不了工作区。"""
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    skill_dir = _write_skill(
        skills_root,
        "stock-check",
        "quantSkills:\n  tags: [stock]\n",
        "See `references/guide.md`.",
    )
    (skill_dir / "references").mkdir()
    (skill_dir / "references" / "guide.md").write_text("", encoding="utf-8")

    capability = audit_skill(skill_dir)

    assert capability.status == "unavailable"
    assert "不会写入工作区" in capability.notes
