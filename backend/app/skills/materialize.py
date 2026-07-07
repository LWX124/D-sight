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


def write_skills(ws: Path, rows: list) -> None:
    """清空重写 {ws}/skills/：卸载与下架在下一次组装即时生效。"""
    dest = ws / "skills"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for row in rows:
        slug = row.slug
        if (not slug or "/" in slug or "\\" in slug or ".." in slug
                or Path(slug).is_absolute()):
            raise ValueError(f"非法 skill slug: {slug!r}")
        d = dest / slug
        assert d.resolve().is_relative_to(dest.resolve())
        d.mkdir()
        (d / "SKILL.md").write_text(row.body, encoding="utf-8")
