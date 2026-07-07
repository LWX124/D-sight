import asyncio

from tests.test_auth_api import _register


async def _auth_headers(client, db_session, email: str) -> dict:
    token = await _register(client, db_session, email)
    return {"Authorization": f"Bearer {token}"}


async def test_thread_crud_flow(client, db_session):
    headers = await _auth_headers(client, db_session, "th-crud@test.dev")

    resp = await client.post("/api/threads/", json={}, headers=headers)
    assert resp.status_code == 201
    created = resp.json()
    tid = created["id"]
    assert created["title"] == "新对话"

    # 第二个 thread B（后建，updated_at 更新）——用于验证重命名后的排序
    tid_b = (await client.post("/api/threads/", json={}, headers=headers)).json()["id"]

    await asyncio.sleep(0.01)  # 确保 updated_at 严格晚于 created_at，避免同毫秒 flaky
    resp = await client.patch(f"/api/threads/{tid}", json={"title": "茅台研究"}, headers=headers)
    assert resp.status_code == 200
    patched = resp.json()
    assert patched["title"] == "茅台研究"
    # PATCH 刷新 updated_at（2b 依赖：会话按最近活跃排序）
    assert patched["updated_at"] > created["updated_at"]

    # 重命名后 A 冒泡到最前（updated_at desc 生效），B 退居其后
    resp = await client.get("/api/threads/", headers=headers)
    assert [t["id"] for t in resp.json()] == [tid, tid_b]

    assert (await client.delete(f"/api/threads/{tid}", headers=headers)).status_code == 204
    assert (await client.delete(f"/api/threads/{tid_b}", headers=headers)).status_code == 204
    resp = await client.get("/api/threads/", headers=headers)
    assert resp.json() == []


async def test_thread_isolation_between_users(client, db_session):
    headers_a = await _auth_headers(client, db_session, "th-a@test.dev")
    headers_b = await _auth_headers(client, db_session, "th-b@test.dev")

    tid = (await client.post("/api/threads/", json={}, headers=headers_a)).json()["id"]

    assert (await client.get("/api/threads/", headers=headers_b)).json() == []
    resp = await client.patch(f"/api/threads/{tid}", json={"title": "x"}, headers=headers_b)
    assert resp.status_code == 404
    assert (await client.delete(f"/api/threads/{tid}", headers=headers_b)).status_code == 404


async def test_threads_require_auth(client):
    assert (await client.get("/api/threads/")).status_code == 401
