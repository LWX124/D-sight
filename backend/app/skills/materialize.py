import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.skills.models import Skill, UserSkill


async def load_installed_skills(db: AsyncSession, user_id) -> list[Skill]:
    return list((await db.execute(
        select(Skill).join(UserSkill, UserSkill.skill_id == Skill.id)
        .where(UserSkill.user_id == user_id, Skill.is_active.is_(True))
        .order_by(Skill.slug)
    )).scalars())


def _already_materialized(dest: Path, rows: list) -> bool:
    """dest 现有 slug 集与每个 SKILL.md 内容都与 rows 完全一致 → 免清空重写。"""
    if not dest.is_dir():
        return False
    want = {row.slug: row.body for row in rows}
    have = {p.name for p in dest.iterdir() if p.is_dir()}
    if have != set(want):
        return False
    for slug, body in want.items():
        f = dest / slug / "SKILL.md"
        if not f.is_file() or f.read_text(encoding="utf-8") != body:
            return False
    return True


def write_skills(ws: Path, rows: list) -> None:
    """清空重写 {ws}/skills/：卸载与下架在下一次组装即时生效。

    内容完全一致时跳过 rmtree+rewrite，消除同 thread 并发 run 的清空竞态。
    """
    for row in rows:
        slug = row.slug
        if (not slug or "/" in slug or "\\" in slug or ".." in slug
                or Path(slug).is_absolute()):
            raise ValueError(f"非法 skill slug: {slug!r}")
    dest = ws / "skills"
    if _already_materialized(dest, rows):
        return
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for row in rows:
        d = dest / row.slug
        assert d.resolve().is_relative_to(dest.resolve())
        d.mkdir()
        (d / "SKILL.md").write_text(row.body, encoding="utf-8")
