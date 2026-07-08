import uuid as _uuid

import pytest
from sqlalchemy import func, select

from app.auth.models import User
from app.skills import seed
from app.skills.models import Skill, UserSkill
from tests.test_auth_api import _register


def test_parse_frontmatter():
    text = '---\nname: dyp-ask\ndescription: "段永平问答"\n---\n\n# 正文'
    meta = seed.parse_skill_md(text, "dyp-ask")
    assert meta["name"] == "dyp-ask" and meta["description"] == "段永平问答"
    assert meta["body"].startswith("---")


def test_parse_missing_frontmatter_falls_back():
    meta = seed.parse_skill_md("# 无 frontmatter", "x-slug")
    assert meta["name"] == "x-slug" and meta["description"] == ""


@pytest.mark.asyncio
async def test_upsert_idempotent_and_preserves_ops_fields(db_session):
    n1 = await seed.upsert_skills(db_session)
    assert n1 == 19
    one = (await db_session.execute(select(Skill).limit(1))).scalar_one()
    one.price = 42
    one.is_active = False
    await db_session.flush()
    n2 = await seed.upsert_skills(db_session)  # 再跑不重复、不覆盖运营字段
    assert n2 == 19
    total = (await db_session.execute(select(func.count()).select_from(Skill))).scalar_one()
    assert total >= 19
    again = await db_session.get(Skill, one.id)
    assert again.price == 42 and again.is_active is False
    assert (await db_session.execute(
        select(Skill).where(Skill.slug == "investment-research")
    )).scalar_one().model_weight == "pro"
    await db_session.rollback()


@pytest.mark.asyncio
async def test_register_auto_installs_defaults(client, db_session):
    await seed.upsert_skills(db_session)
    await db_session.commit()
    email = f"auto-{_uuid.uuid4()}@t.dev"
    # _register 走完整注册流（request-code -> 从 DB 取码 -> register），返回 access_token。
    await _register(client, db_session, email)
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    n = (await db_session.execute(
        select(func.count()).select_from(UserSkill).where(UserSkill.user_id == user.id)
    )).scalar_one()
    assert n >= 19
