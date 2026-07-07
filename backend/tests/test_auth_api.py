from sqlalchemy import select

from app.auth.models import RefreshToken, User, VerificationCode

REFRESH_COOKIE = "dsight_refresh"


async def _register(client, db_session, email: str, password: str = "pw-123456") -> str:
    """走完整注册流，返回 access_token。"""
    resp = await client.post("/api/auth/request-code", json={"email": email})
    # 正常模式 204；FAKE_LLM 模式（如聊天用例夹具）走后门返回 200 + debug_code。
    assert resp.status_code in (200, 204)
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
    saved = client.cookies[REFRESH_COOKIE]
    assert (await client.post("/api/auth/logout")).status_code == 204

    # logout 清空了 cookie jar；手动带回原 cookie，401 必须是"已吊销"而非"缺 cookie"。
    client.cookies.set(REFRESH_COOKIE, saved, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401

    # DB 层确认该用户的 refresh token 确实被吊销。
    rows = (
        await db_session.scalars(
            select(RefreshToken).join(User, User.id == RefreshToken.user_id).where(
                User.email == "api-logout@test.dev"
            )
        )
    ).all()
    assert rows and all(r.revoked_at is not None for r in rows)


async def test_register_password_too_long_returns_422(client, db_session):
    email = "api-longpw@test.dev"
    resp = await client.post("/api/auth/request-code", json={"email": email})
    # 正常模式 204；FAKE_LLM 模式（如聊天用例夹具）走后门返回 200 + debug_code。
    assert resp.status_code in (200, 204)
    code = (
        await db_session.scalar(
            select(VerificationCode)
            .where(VerificationCode.email == email)
            .order_by(VerificationCode.created_at.desc())
            .limit(1)
        )
    ).code
    # 25 个汉字 = 75 字节 > bcrypt 72 字节上限。
    resp = await client.post(
        "/api/auth/register", json={"email": email, "code": code, "password": "密" * 25}
    )
    assert resp.status_code == 422


async def test_request_code_no_body_in_normal_mode(client, monkeypatch):
    # 正常模式（FAKE_LLM 关）：204 无体，绝不泄漏验证码。显式关 fake，
    # 不依赖其他用例遗留的缓存状态。
    from app.core import config

    monkeypatch.setenv("FAKE_LLM", "0")
    config.get_settings.cache_clear()
    try:
        resp = await client.post(
            "/api/auth/request-code", json={"email": "normal-mode@test.dev"}
        )
        assert resp.status_code == 204
        assert resp.content == b""
    finally:
        config.get_settings.cache_clear()


async def test_request_code_debug_backdoor_in_fake_mode(client, monkeypatch):
    from app.core import config

    monkeypatch.setenv("FAKE_LLM", "1")
    config.get_settings.cache_clear()
    try:
        resp = await client.post(
            "/api/auth/request-code", json={"email": "fake-mode@test.dev"}
        )
        assert resp.status_code == 200
        code = resp.json()["debug_code"]
        assert len(code) == 6 and code.isdigit()
    finally:
        # 清缓存，避免 fake 状态泄漏到后续用例（否则它们仍读到 fake_llm=True）。
        config.get_settings.cache_clear()


async def test_login_overlong_password_not_500(client, db_session):
    await _register(client, db_session, "api-loginlong@test.dev")
    # 超长密码走 schema 校验返回 422；即便绕过也应 401——总之绝不能 500。
    resp = await client.post(
        "/api/auth/login",
        json={"email": "api-loginlong@test.dev", "password": "密" * 25},
    )
    assert resp.status_code in (401, 422)
    assert resp.status_code != 500
