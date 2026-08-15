#!/usr/bin/env python3
"""Audit stock-related skills and their declared/local dependencies."""

from __future__ import annotations

import re
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

STOCK_KEYWORDS = {"stock", "diagnosis", "financial", "investment", "portfolio"}
PATH_KINDS = {"references", "scripts", "tools"}
KIND_ALIASES = {
    "references": "reference",
    "reference": "reference",
    "scripts": "script",
    "script": "script",
    "tools": "tool",
    "tool": "tool",
    "skills": "skill",
    "skill": "skill",
}


@dataclass(frozen=True)
class Dependency:
    """One dependency and the capability semantics of its absence."""

    path: str
    kind: str
    required: bool = True
    degraded_capable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SkillCapability:
    skill_id: str
    status: str
    dependencies: list[Dependency]
    materialized_dependencies: list[Dependency]
    missing_dependencies: list[Dependency]
    last_verified: Optional[str] = None
    notes: Optional[str] = None

    @property
    def declared_dependencies(self) -> list[str]:
        return [dependency.path for dependency in self.dependencies]

    @property
    def tools_used(self) -> list[str]:
        return [dependency.path for dependency in self.dependencies if dependency.kind == "tool"]

    @property
    def scripts_used(self) -> list[str]:
        return [dependency.path for dependency in self.dependencies if dependency.kind == "script"]

    @property
    def reference_files(self) -> list[str]:
        return [dependency.path for dependency in self.dependencies if dependency.kind == "reference"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "status": self.status,
            "dependencies": [dependency.to_dict() for dependency in self.dependencies],
            "materialized_dependencies": [
                dependency.to_dict() for dependency in self.materialized_dependencies
            ],
            "missing_dependencies": [
                dependency.to_dict() for dependency in self.missing_dependencies
            ],
            "last_verified": self.last_verified,
            "notes": self.notes,
        }


def _frontmatter(content: str) -> dict[str, Any]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.S)
    if not match:
        return {}
    try:
        parsed = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _declared_dependencies(frontmatter: dict[str, Any]) -> list[Dependency]:
    quant = frontmatter.get("quantSkills")
    raw_dependencies = quant.get("requires", []) if isinstance(quant, dict) else []
    dependencies: list[Dependency] = []
    for raw in raw_dependencies or []:
        if isinstance(raw, str):
            dependencies.append(Dependency(path=raw, kind="skill"))
        elif isinstance(raw, dict):
            path = raw.get("id") or raw.get("path") or raw.get("name")
            if path:
                dependencies.append(
                    Dependency(
                        path=str(path),
                        kind=KIND_ALIASES.get(
                            str(raw.get("kind", "skill")).lower(),
                            str(raw.get("kind", "skill")).lower(),
                        ),
                        required=bool(raw.get("required", True)),
                        degraded_capable=bool(raw.get("degraded_capable", False)),
                    )
                )
    return dependencies


def _normalize_resource(token: str) -> tuple[str, str] | None:
    token = token.rstrip(".,;:)").split("#", 1)[0]
    for directory in PATH_KINDS:
        marker = f"{directory}/"
        if marker in token:
            path = token[token.index(marker) :]
            return path, directory[:-1] if directory != "references" else "reference"
    return None


def _body_dependencies(content: str) -> list[Dependency]:
    found: dict[str, Dependency] = {}
    for code in re.findall(r"`([^`\n]+)`", content):
        try:
            tokens = shlex.split(code)
        except ValueError:
            tokens = code.split()
        for token in tokens:
            normalized = _normalize_resource(token)
            if normalized:
                path, kind = normalized
                found[path] = Dependency(path=path, kind=kind)
    return [found[path] for path in sorted(found)]


def parse_skill_md(file_path: Path) -> dict[str, Any]:
    """Parse metadata and normalize every dependency into one contract."""
    content = file_path.read_text(encoding="utf-8")
    frontmatter = _frontmatter(content)
    body_dependencies = {
        dependency.path: dependency for dependency in _body_dependencies(content)
    }
    declared_dependencies = {
        dependency.path: dependency
        for dependency in _declared_dependencies(frontmatter)
    }
    dependencies = {**body_dependencies, **declared_dependencies}
    return {
        "name": frontmatter.get("name", file_path.parent.name),
        "frontmatter": frontmatter,
        "dependencies": [dependencies[path] for path in sorted(dependencies)],
    }


def _resolve(skill_dir: Path, dependency: Dependency) -> tuple[Path | None, str | None]:
    """依赖在**运行时**能否被取到，而不是它在仓库里存不存在。

    运行时的事实（app/skills/materialize.py、app/agent/workspace.py）：
      - 每个会话工作区只写入 `skills/<slug>/SKILL.md`，skill 目录里的
        references/ 与 scripts/ 永远不会落盘；
      - `tools/` 是全局共享目录，从 skills_data/tools 整体拷进工作区，
        所以 `python3 tools/xxx.py` 是可用的。

    按 skill 目录去找 tools/ 会把可用的判成缺失，按仓库文件是否存在去判
    references/ 又会把不可用的判成可用——两个方向都错，故按运行时规则解析。

    返回 (待检查路径, 不可达原因)；两者必有其一为 None。
    """
    if dependency.kind == "skill":
        return skill_dir.parent / dependency.path / "SKILL.md", None
    if dependency.path.startswith("tools/"):
        return skill_dir.parent.parent / dependency.path, None
    return None, "skill 目录内的文件不会写入工作区，运行时取不到"


def audit_skill(skill_dir: Path) -> SkillCapability:
    """Return structured capability state for one skill."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        missing = Dependency(path="SKILL.md", kind="skill")
        return SkillCapability(
            skill_id=skill_dir.name,
            status="unavailable",
            dependencies=[missing],
            materialized_dependencies=[],
            missing_dependencies=[missing],
            notes="Missing: SKILL.md",
        )

    parsed = parse_skill_md(skill_md)
    materialized: list[Dependency] = []
    missing: list[Dependency] = []
    reasons: list[str] = []
    for dependency in parsed["dependencies"]:
        target, unreachable = _resolve(skill_dir, dependency)
        if unreachable is not None:
            missing.append(dependency)
            reasons.append(f"{dependency.path}（{unreachable}）")
        elif target.exists():
            materialized.append(dependency)
        else:
            missing.append(dependency)
            reasons.append(f"{dependency.path}（不存在）")

    blocking = [
        dependency
        for dependency in missing
        if dependency.required and not dependency.degraded_capable
    ]
    status = "unavailable" if blocking else "degraded" if missing else "runnable"
    notes = f"Missing: {', '.join(reasons)}" if reasons else None
    return SkillCapability(
        skill_id=skill_dir.name,
        status=status,
        dependencies=parsed["dependencies"],
        materialized_dependencies=materialized,
        missing_dependencies=missing,
        notes=notes,
    )


def _structured_stock_metadata(frontmatter: dict[str, Any]) -> bool | None:
    quant = frontmatter.get("quantSkills")
    if not isinstance(quant, dict):
        return None
    tags = quant.get("tags")
    if not isinstance(tags, list):
        return None
    normalized = {str(tag).lower() for tag in tags}
    return bool(normalized & STOCK_KEYWORDS or {"a-share", "stock-dossier"} & normalized)


def discover_stock_skills(skills_dir: Path) -> list[Path]:
    """Prefer structured tags; keyword-search only legacy metadata/body."""
    discovered: list[Path] = []
    if not skills_dir.exists():
        return discovered
    for skill_dir in sorted(skills_dir.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        content = skill_md.read_text(encoding="utf-8")
        frontmatter = _frontmatter(content)
        structured = _structured_stock_metadata(frontmatter)
        if structured is True:
            discovered.append(skill_dir)
        elif structured is None:
            metadata_text = " ".join(
                str(frontmatter.get(field, "")) for field in ("name", "description")
            ).lower()
            if any(keyword in metadata_text for keyword in STOCK_KEYWORDS):
                discovered.append(skill_dir)
    return discovered


def audit_skills(skills_dir: Path) -> list[SkillCapability]:
    return [audit_skill(skill_dir) for skill_dir in discover_stock_skills(skills_dir)]


def _print_report(capabilities: list[SkillCapability]) -> None:
    print(f"Found {len(capabilities)} stock-related skills")
    print("=" * 80)
    for capability in capabilities:
        print(f"\nSkill: {capability.skill_id}")
        print(f"Status: {capability.status}")
        print(f"Declared Dependencies: {capability.declared_dependencies}")
        print(
            "Materialized: "
            f"{[dependency.path for dependency in capability.materialized_dependencies]}"
        )
        print(f"Missing: {[dependency.path for dependency in capability.missing_dependencies]}")
        if capability.notes:
            print(f"Notes: {capability.notes}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    for status in ("runnable", "degraded", "unavailable"):
        label = status.capitalize()
        print(f"{label}: {sum(item.status == status for item in capabilities)}")


def main(skills_dir: Optional[Path] = None) -> list[SkillCapability]:
    if skills_dir is None:
        skills_dir = Path(__file__).resolve().parents[3] / "skills_data" / "skills"
    capabilities = audit_skills(skills_dir)
    _print_report(capabilities)
    return capabilities


if __name__ == "__main__":
    main()
