import uuid

import pytest

from app.auth.models import User
from app.core.security import hash_password
from app.skills.models import Skill, UserSkill


@pytest.mark.asyncio
async def test_skill_and_install_roundtrip(db_session):
    s = Skill(slug=f"t-{uuid.uuid4().hex[:8]}", name="测试技能", body="---\nname: t\n---\n正文")
    u = User(email=f"sk-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add_all([s, u])
    await db_session.flush()
    db_session.add(UserSkill(user_id=u.id, skill_id=s.id))
    await db_session.commit()
    got = await db_session.get(Skill, s.id)
    assert got.price == 0 and got.is_active and got.model_weight == "flash"


@pytest.mark.asyncio
async def test_duplicate_install_rejected(db_session):
    from sqlalchemy.exc import IntegrityError
    s = Skill(slug=f"d-{uuid.uuid4().hex[:8]}", name="d", body="b")
    u = User(email=f"dup-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add_all([s, u])
    await db_session.flush()
    db_session.add(UserSkill(user_id=u.id, skill_id=s.id))
    await db_session.flush()
    db_session.add(UserSkill(user_id=u.id, skill_id=s.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
