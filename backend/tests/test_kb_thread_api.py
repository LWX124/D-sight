import uuid

import pytest

from app.threads.models import Thread
from tests.conftest import _auth


@pytest.mark.asyncio
async def test_thread_is_created_once_per_kb(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "对话库"}, headers=h)).json()["id"]

    first = (await client.get(f"/api/kb/{kb_id}/thread", headers=h)).json()["thread_id"]
    second = (await client.get(f"/api/kb/{kb_id}/thread", headers=h)).json()["thread_id"]
    assert first == second                       # 常驻，不是每次新建

    t = await db_session.get(Thread, uuid.UUID(first))
    assert t.type == "kb" and t.ref_id == uuid.UUID(kb_id)
    assert t.user_id == registered_user.id


@pytest.mark.asyncio
async def test_each_kb_gets_its_own_thread(client, registered_user):
    h = _auth(registered_user)
    kb1 = (await client.post("/api/kb", json={"name": "库A"}, headers=h)).json()["id"]
    kb2 = (await client.post("/api/kb", json={"name": "库B"}, headers=h)).json()["id"]
    t1 = (await client.get(f"/api/kb/{kb1}/thread", headers=h)).json()["thread_id"]
    t2 = (await client.get(f"/api/kb/{kb2}/thread", headers=h)).json()["thread_id"]
    assert t1 != t2


@pytest.mark.asyncio
async def test_kb_thread_absent_from_global_thread_list(client, registered_user):
    """type != "chat" 的会话不进左侧全局会话列表，与新闻助手一致。"""
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "隐藏库"}, headers=h)).json()["id"]
    tid = (await client.get(f"/api/kb/{kb_id}/thread", headers=h)).json()["thread_id"]
    listed = (await client.get("/api/threads/", headers=h)).json()
    assert tid not in [t["id"] for t in listed]


@pytest.mark.asyncio
async def test_thread_on_foreign_kb_is_404(client, registered_user):
    h = _auth(registered_user)
    r = await client.get("/api/kb/00000000-0000-0000-0000-000000000000/thread", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_thread_recreated_after_soft_delete(client, registered_user):
    """清除对话：软删后再取会得到新 id（前端据此重建 runtime 清空历史）。"""
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "清空库"}, headers=h)).json()["id"]
    old = (await client.get(f"/api/kb/{kb_id}/thread", headers=h)).json()["thread_id"]
    assert (await client.delete(f"/api/threads/{old}", headers=h)).status_code == 204
    new = (await client.get(f"/api/kb/{kb_id}/thread", headers=h)).json()["thread_id"]
    assert new != old
