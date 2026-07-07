import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.workspace import SKILLS_DATA
from app.auth.models import User
from app.skills.models import Skill, UserSkill

PRO_SLUGS = {"investment-research", "deep-company-series"}
_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def parse_skill_md(text: str, slug: str) -> dict:
    name, description = slug, ""
    m = _FM.match(text)
    if m:
        for line in m.group(1).splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip().strip('"') or slug
            elif line.startswith("description:"):
                description = line.split(":", 1)[1].strip().strip('"')
    return {"name": name, "description": description, "body": text}


async def upsert_skills(db: AsyncSession) -> int:
    root = SKILLS_DATA / "skills"
    count = 0
    for d in sorted(p for p in root.iterdir() if (p / "SKILL.md").is_file()):
        slug = d.name
        meta = parse_skill_md((d / "SKILL.md").read_text(encoding="utf-8"), slug)
        existing = (await db.execute(select(Skill).where(Skill.slug == slug))).scalar_one_or_none()
        if existing is None:
            db.add(Skill(
                slug=slug, name=meta["name"], description=meta["description"], body=meta["body"],
                model_weight="pro" if slug in PRO_SLUGS else "flash",
            ))
        else:  # 只刷新内容字段，运营字段（price/is_active/...）不动
            existing.name, existing.description, existing.body = meta["name"], meta["description"], meta["body"]
        count += 1
    await db.flush()
    return count


async def install_defaults(db: AsyncSession, user_id) -> int:
    skills = (await db.execute(
        select(Skill).where(Skill.is_default.is_(True), Skill.is_active.is_(True))
    )).scalars().all()
    installed = {
        us.skill_id for us in (await db.execute(
            select(UserSkill).where(UserSkill.user_id == user_id)
        )).scalars()
    }
    n = 0
    for s in skills:
        if s.id not in installed:
            db.add(UserSkill(user_id=user_id, skill_id=s.id))
            n += 1
    await db.flush()
    return n


async def install_defaults_for_all_users(db: AsyncSession) -> int:
    n = 0
    for user in (await db.execute(select(User))).scalars():
        n += await install_defaults(db, user.id)
    await db.flush()
    return n
