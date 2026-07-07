from tests.test_auth_api import _register


async def _auth_headers(client, db_session, email: str) -> dict:
    token = await _register(client, db_session, email)
    return {"Authorization": f"Bearer {token}"}


async def test_thread_crud_flow(client, db_session):
    headers = await _auth_headers(client, db_session, "th-crud@test.dev")

    resp = await client.post("/api/threads/", json={}, headers=headers)
    assert resp.status_code == 201
    tid = resp.json()["id"]
    assert resp.json()["title"] == "新对话"

    resp = await client.patch(f"/api/threads/{tid}", json={"title": "茅台研究"}, headers=headers)
    assert resp.status_code == 200 and resp.json()["title"] == "茅台研究"

    resp = await client.get("/api/threads/", headers=headers)
    assert [t["id"] for t in resp.json()] == [tid]

    assert (await client.delete(f"/api/threads/{tid}", headers=headers)).status_code == 204
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
