from sqlalchemy import select

from app.auth.models import VerificationCode

REFRESH_COOKIE = "dsight_refresh"


async def _register(client, db_session, email: str, password: str = "pw-123456") -> str:
    """走完整注册流，返回 access_token。"""
    resp = await client.post("/api/auth/request-code", json={"email": email})
    assert resp.status_code == 204
    code = (
        await db_session.scalar(
            select(VerificationCode)
            .where(VerificationCode.email == email)
            .order_by(VerificationCode.created_at.desc())
            .limit(1)
        )
    ).code
    resp = await client.post(
        "/api/auth/register", json={"email": email, "code": code, "password": password}
    )
    assert resp.status_code == 201, resp.text
    assert REFRESH_COOKIE in resp.cookies
    return resp.json()["access_token"]


async def test_register_then_me(client, db_session):
    token = await _register(client, db_session, "api-reg@test.dev")
    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "api-reg@test.dev" and body["role"] == "user"


async def test_me_requires_token(client):
    assert (await client.get("/api/auth/me")).status_code == 401
    resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer bogus"})
    assert resp.status_code == 401


async def test_login_and_refresh_rotation(client, db_session):
    await _register(client, db_session, "api-login@test.dev")
    resp = await client.post(
        "/api/auth/login", json={"email": "api-login@test.dev", "password": "pw-123456"}
    )
    assert resp.status_code == 200
    old_cookie = resp.cookies[REFRESH_COOKIE]

    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 200
    assert resp.json()["access_token"]
    assert resp.cookies[REFRESH_COOKIE] != old_cookie  # 轮换

    # 旧 refresh 已吊销：手动带旧 cookie 再刷新应 401
    client.cookies.set(REFRESH_COOKIE, old_cookie, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_logout_revokes_refresh(client, db_session):
    await _register(client, db_session, "api-logout@test.dev")
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.post("/api/auth/refresh")).status_code == 401
