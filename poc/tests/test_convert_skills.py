from pathlib import Path

from poc.convert_skills import convert_skill, extract_meta

DEMO = """# 演示技能：示例分析框架

对 $ARGUMENTS 进行演示分析。

## 第一步

做点什么。
"""


def test_extract_meta():
    title, desc = extract_meta(DEMO, "demo-skill")
    assert title == "演示技能：示例分析框架"
    assert "演示分析" in desc
    assert "$ARGUMENTS" not in desc  # 描述里不能留模板变量


def test_convert_skill(tmp_path: Path):
    src = tmp_path / "demo-skill.md"
    src.write_text(DEMO, encoding="utf-8")
    out = convert_skill(src, tmp_path / "ws")
    assert out == tmp_path / "ws" / "skills" / "demo-skill" / "SKILL.md"
    text = out.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "---"
    assert lines[1] == "name: demo-skill"
    assert lines[2].startswith('description: "')
    assert lines[3] == "---"
    assert "对 $ARGUMENTS 进行演示分析。" in text  # 正文原样保留
