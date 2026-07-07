import pytest
from sqlalchemy import select

from app.skills import seed
from app.skills.models import Skill


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {user.token}"}


@pytest.fixture
async def seeded(db_session):
    await seed.upsert_skills(db_session)
    await db_session.commit()


@pytest.mark.asyncio
async def test_list_marks_installed(client, db_session, seeded, registered_user):
    r = await client.get("/api/skills", headers=_auth(registered_user))
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 19
    assert all(i["installed"] for i in items)  # 注册自动装了默认 skill


@pytest.mark.asyncio
async def test_detail_and_install_cycle(client, db_session, seeded, registered_user):
    h = _auth(registered_user)
    d = await client.get("/api/skills/dyp-ask", headers=h)
    assert d.status_code == 200 and d.json()["body"].startswith("---")
    r1 = await client.delete("/api/skills/dyp-ask/install", headers=h)
    assert r1.json() == {"installed": False}
    lst = await client.get("/api/skills", headers=h)
    assert next(i for i in lst.json() if i["slug"] == "dyp-ask")["installed"] is False
    r2 = await client.post("/api/skills/dyp-ask/install", headers=h)
    assert r2.json() == {"installed": True}
    r3 = await client.post("/api/skills/dyp-ask/install", headers=h)  # 幂等
    assert r3.status_code == 200


@pytest.mark.asyncio
async def test_inactive_hidden_and_404(client, db_session, seeded, registered_user):
    h = _auth(registered_user)
    s = (await db_session.execute(select(Skill).where(Skill.slug == "dyp-ask"))).scalar_one()
    s.is_active = False
    await db_session.commit()
    lst = await client.get("/api/skills", headers=h)
    assert all(i["slug"] != "dyp-ask" for i in lst.json())
    assert (await client.get("/api/skills/dyp-ask", headers=h)).status_code == 404
    assert (await client.post("/api/skills/dyp-ask/install", headers=h)).status_code == 404
    s.is_active = True
    await db_session.commit()
