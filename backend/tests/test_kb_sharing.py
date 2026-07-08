import uuid

import pytest

from app.auth.models import User
from app.core.security import create_access_token, hash_password
from app.kb.retrieval import accessible_kb_ids
from tests.conftest import _auth


async def _second_user(db_session) -> User:
    other = User(email=f"o-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add(other)
    await db_session.commit()
    other.token = create_access_token(str(other.id))
    return other


@pytest.mark.asyncio
async def test_share_subscribe_and_revoke(client, db_session, registered_user):
    owner_h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "共享库"}, headers=owner_h)).json()["id"]
    slug = (await client.post(f"/api/kb/{kb_id}/share", headers=owner_h)).json()["share_slug"]

    # 另一个用户订阅
    other = await _second_user(db_session)
    oh = _auth(other)
    sub = await client.post(f"/api/kb/subscribe/{slug}", headers=oh)
    assert sub.status_code == 200 and sub.json()["kb_id"] == kb_id
    assert any(k["id"] == kb_id for k in (await client.get("/api/kb/subscribed", headers=oh)).json())
    assert await accessible_kb_ids(db_session, other.id, [uuid.UUID(kb_id)]) == [uuid.UUID(kb_id)]

    # owner 撤销共享 → 订阅失效
    await client.delete(f"/api/kb/{kb_id}/share", headers=owner_h)
    assert await accessible_kb_ids(db_session, other.id, [uuid.UUID(kb_id)]) == []
    assert (await client.get("/api/kb/subscribed", headers=oh)).json() == []


@pytest.mark.asyncio
async def test_cannot_subscribe_own_and_bad_slug(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "自有"}, headers=h)).json()["id"]
    slug = (await client.post(f"/api/kb/{kb_id}/share", headers=h)).json()["share_slug"]
    assert (await client.post(f"/api/kb/subscribe/{slug}", headers=h)).status_code == 400
    assert (await client.post("/api/kb/subscribe/deadbeef", headers=h)).status_code == 404
