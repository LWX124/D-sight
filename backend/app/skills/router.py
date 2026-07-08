from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.db import get_db
from app.skills.models import Skill, UserSkill
from app.skills.schemas import SkillDetail, SkillOut

router = APIRouter(prefix="/api/skills", tags=["skills"])


async def _active_skill(db: AsyncSession, slug: str) -> Skill:
    s = (await db.execute(
        select(Skill).where(Skill.slug == slug, Skill.is_active.is_(True))
    )).scalar_one_or_none()
    if s is None:
        raise HTTPException(404, "skill 不存在")
    return s


async def _installed_ids(db: AsyncSession, user_id) -> set:
    return {
        us.skill_id for us in (await db.execute(
            select(UserSkill).where(UserSkill.user_id == user_id)
        )).scalars()
    }


def _out(s: Skill, installed: bool) -> dict:
    return {
        "slug": s.slug, "name": s.name, "description": s.description,
        "category": s.category, "price": s.price, "model_weight": s.model_weight,
        "is_default": s.is_default, "installed": installed,
    }


@router.get("", response_model=list[SkillOut])
async def list_skills(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    skills = (await db.execute(
        select(Skill).where(Skill.is_active.is_(True)).order_by(Skill.slug)
    )).scalars().all()
    installed = await _installed_ids(db, user.id)
    return [_out(s, s.id in installed) for s in skills]


@router.get("/{slug}", response_model=SkillDetail)
async def skill_detail(slug: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s = await _active_skill(db, slug)
    installed = await _installed_ids(db, user.id)
    return {**_out(s, s.id in installed), "body": s.body}


@router.post("/{slug}/install")
async def install(slug: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s = await _active_skill(db, slug)
    if s.id not in await _installed_ids(db, user.id):
        db.add(UserSkill(user_id=user.id, skill_id=s.id))
        await db.commit()
    return {"installed": True}


@router.delete("/{slug}/install")
async def uninstall(slug: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s = await _active_skill(db, slug)
    for us in (await db.execute(
        select(UserSkill).where(UserSkill.user_id == user.id, UserSkill.skill_id == s.id)
    )).scalars():
        await db.delete(us)
    await db.commit()
    return {"installed": False}
