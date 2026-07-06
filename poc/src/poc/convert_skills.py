"""把 ai-berkshire 的 skill md 转成 Agent Skills 规范（SKILL.md + frontmatter）工作区。"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

AI_BERKSHIRE = Path("/Users/weixi1/Documents/Study/ai-berkshire")
POC_SKILLS = ["investment-research", "financial-data"]


def extract_meta(md_text: str, slug: str) -> tuple[str, str]:
    """返回 (title, description)。title 取首个一级标题，description 取标题后首段非空文本。"""
    lines = md_text.splitlines()
    title = slug
    description = ""
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            for rest in lines[i + 1 :]:
                text = rest.strip()
                if text and not text.startswith("#"):
                    description = text
                    break
            break
    description = description or title
    description = description.replace("$ARGUMENTS", "用户指定的目标")
    return title, description[:500]


def convert_skill(src_md: Path, dest_root: Path) -> Path:
    slug = src_md.stem
    md_text = src_md.read_text(encoding="utf-8")
    title, description = extract_meta(md_text, slug)
    desc_line = f"{title}：{description}".replace('"', "'")
    skill_dir = dest_root / "skills" / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    out = skill_dir / "SKILL.md"
    out.write_text(
        f'---\nname: {slug}\ndescription: "{desc_line}"\n---\n\n{md_text}',
        encoding="utf-8",
    )
    return out


def build_workspace(dest_root: Path, skills: list[str]) -> None:
    for slug in skills:
        convert_skill(AI_BERKSHIRE / "skills" / f"{slug}.md", dest_root)
    tools_dst = dest_root / "tools"
    tools_dst.mkdir(parents=True, exist_ok=True)
    for py in (AI_BERKSHIRE / "tools").glob("*.py"):
        shutil.copy(py, tools_dst / py.name)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2] / "workspace"
    build_workspace(root, POC_SKILLS)
    print(f"workspace ready: {root}")
