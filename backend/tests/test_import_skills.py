from pathlib import Path

from scripts.import_skills import convert_skill, extract_meta

DEMO = """# 演示技能：示例分析框架

对 $ARGUMENTS 进行演示分析。

## 第一步

做点什么。
"""


def test_extract_meta():
    title, desc = extract_meta(DEMO, "demo-skill")
    assert title == "演示技能：示例分析框架"
    assert "演示分析" in desc
    assert "$ARGUMENTS" not in desc


def test_convert_skill(tmp_path: Path):
    src = tmp_path / "demo-skill.md"
    src.write_text(DEMO, encoding="utf-8")
    out = convert_skill(src, tmp_path / "assets")
    assert out == tmp_path / "assets" / "skills" / "demo-skill" / "SKILL.md"
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---" and lines[1] == "name: demo-skill"
    assert lines[2].startswith('description: "')


def test_generated_assets_present():
    """入库的生成产物必须存在且完整（防 fresh clone 空目录静默）。"""
    root = Path(__file__).resolve().parents[1] / "skills_data"
    skills = list((root / "skills").glob("*/SKILL.md"))
    assert len(skills) == 19
    assert (root / "tools" / "financial_rigor.py").exists()
    audit = (root / "tools" / "report_audit.py").read_text(encoding="utf-8")
    assert "--results-file" in audit  # PoC 输入#4：补丁已打
