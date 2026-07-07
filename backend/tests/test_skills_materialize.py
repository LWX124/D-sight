import pytest

from app.skills import seed
from app.skills.materialize import load_installed_skills, write_skills


@pytest.mark.asyncio
async def test_write_skills_clears_and_writes(tmp_path):
    class Row:
        def __init__(self, slug, body):
            self.slug, self.body = slug, body
    ws = tmp_path
    (ws / "skills" / "stale").mkdir(parents=True)
    write_skills(ws, [Row("a", "A正文"), Row("b", "B正文")])
    assert (ws / "skills" / "a" / "SKILL.md").read_text(encoding="utf-8") == "A正文"
    assert not (ws / "skills" / "stale").exists()  # 旧内容被清
    write_skills(ws, [Row("a", "A正文")])  # 卸载 b
    assert not (ws / "skills" / "b").exists()


@pytest.mark.asyncio
async def test_write_skills_rejects_bad_slug(tmp_path):
    class Row:
        def __init__(self, slug, body="x"):
            self.slug, self.body = slug, body
    for bad in ("../esc", "/abs", "a/b", ""):
        with pytest.raises(ValueError):
            write_skills(tmp_path, [Row(bad)])
    # 拒绝后不得留下越界文件
    assert not (tmp_path.parent / "esc").exists()


@pytest.mark.asyncio
async def test_load_installed_excludes_inactive(db_session, registered_user):
    from sqlalchemy import select
    from app.skills.models import Skill
    await seed.upsert_skills(db_session)
    from app.skills.seed import install_defaults
    await install_defaults(db_session, registered_user.id)
    await db_session.commit()
    rows = await load_installed_skills(db_session, registered_user.id)
    assert len(rows) >= 19
    s = (await db_session.execute(select(Skill).where(Skill.slug == "dyp-ask"))).scalar_one()
    s.is_active = False
    await db_session.commit()
    rows2 = await load_installed_skills(db_session, registered_user.id)
    assert all(r.slug != "dyp-ask" for r in rows2)
    s.is_active = True
    await db_session.commit()
