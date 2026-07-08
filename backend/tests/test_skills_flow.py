import uuid as _uuid

import pytest
from sqlalchemy import select

from app.agent.workspace import get_thread_workspace
from app.skills import seed
from app.skills.materialize import load_installed_skills, write_skills
from app.skills.models import Skill, SkillFile


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {user.token}"}


@pytest.mark.asyncio
async def test_uninstall_excludes_from_assembly(client, db_session, registered_user):
    """闭环：注册自动装 → 卸载 → 下次组装物化不含该 skill。"""
    await seed.upsert_skills(db_session)
    from app.skills.seed import install_defaults

    await install_defaults(db_session, registered_user.id)
    await db_session.commit()
    h = _auth(registered_user)

    rows = await load_installed_skills(db_session, registered_user.id)
    assert any(r.slug == "dyp-ask" for r in rows)

    resp = await client.delete("/api/skills/dyp-ask/install", headers=h)
    assert resp.status_code == 200

    rows2 = await load_installed_skills(db_session, registered_user.id)
    assert all(r.slug != "dyp-ask" for r in rows2)

    # 物化落盘验证：卸载即时生效，earnings-review 仍在。
    tid = str(_uuid.uuid4())
    ws = get_thread_workspace(tid)
    write_skills(ws, rows2)
    assert not (ws / "skills" / "dyp-ask").exists()
    assert (ws / "skills" / "earnings-review" / "SKILL.md").exists()


@pytest.mark.asyncio
async def test_skill_file_cascade_delete(db_session):
    """T1 gap：SkillFile 往返 + 父 Skill 删除级联清除附属文件。"""
    throwaway = Skill(
        slug=f"throwaway-{_uuid.uuid4().hex[:8]}",
        name="一次性",
        description="",
        body="正文",
    )
    db_session.add(throwaway)
    await db_session.flush()

    sf = SkillFile(skill_id=throwaway.id, path="ref.md", content="附属")
    db_session.add(sf)
    await db_session.flush()

    read_back = (
        await db_session.execute(select(SkillFile).where(SkillFile.id == sf.id))
    ).scalar_one()
    assert read_back.path == "ref.md"
    assert read_back.content == "附属"
    assert read_back.skill_id == throwaway.id

    await db_session.delete(throwaway)
    await db_session.flush()
    gone = (
        await db_session.execute(select(SkillFile).where(SkillFile.id == sf.id))
    ).scalar_one_or_none()
    assert gone is None  # ondelete=CASCADE
    await db_session.rollback()


@pytest.mark.asyncio
async def test_seeded_skill_is_default(db_session):
    """T1 gap：种子 skill 默认安装（is_default=True）。"""
    await seed.upsert_skills(db_session)
    await db_session.commit()
    s = (
        await db_session.execute(select(Skill).where(Skill.slug == "dyp-ask"))
    ).scalar_one()
    assert s.is_default is True
