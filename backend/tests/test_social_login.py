import uuid

import httpx
import pytest
from sqlalchemy import select

from app.auth.models import User  # noqa: F401 — 注册 users 表以解析 FK
from app.social.models import WechatCredential


@pytest.mark.asyncio
async def test_poll_confirmed_stores_encrypted_credential(db_session, monkeypatch):
    from app.social import crypto
    from app.social.wechat import login, session_store

    async def fake_load(sid):
        return "uuid=UU"
    async def fake_delete(sid):
        return None
    monkeypatch.setattr(session_store, "load", fake_load)
    monkeypatch.setattr(session_store, "delete", fake_delete)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "scanloginqrcode" in url and "action=ask" in url:
            return httpx.Response(200, json={"status": 1, "acct_size": 1, "base_resp": {"ret": 0}})
        if "bizlogin" in url:
            return httpx.Response(
                200,
                json={"base_resp": {"ret": 0}, "redirect_url": "/cgi-bin/home?token=TK123&lang=zh_CN"},
                headers={"set-cookie": "slave_sid=SS; Path=/"},
            )
        if "action=info" in url or "cgi-bin/info" in url:
            return httpx.Response(200, json={"base_resp": {"ret": 0}, "nick_name": "我的号", "head_img": "http://a"})
        return httpx.Response(200, json={"base_resp": {"ret": 0}})

    monkeypatch.setattr(login, "new_mp_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    from app.core.security import hash_password
    user_id = uuid.uuid4()
    u = User(id=user_id, email=f"login-{user_id.hex[:6]}@t.dev", password_hash=hash_password("x"))
    db_session.add(u)
    await db_session.commit()

    res = await login.poll_status(db_session, "sess-1", user_id)
    assert res["status"] == "confirmed"
    assert res["nickname"] == "我的号"

    cred = await db_session.scalar(select(WechatCredential).where(WechatCredential.user_id == user_id))
    assert cred is not None
    assert cred.status == "active"
    assert crypto.decrypt(cred.token) == "TK123"
    assert "slave_sid=SS" in crypto.decrypt(cred.cookies)


@pytest.mark.asyncio
async def test_poll_waiting_when_not_scanned(db_session, monkeypatch):
    from app.social.wechat import login, session_store

    async def fake_load(sid):
        return "uuid=UU"
    monkeypatch.setattr(session_store, "load", fake_load)

    def handler(request):
        return httpx.Response(200, json={"status": 0, "base_resp": {"ret": 0}})
    monkeypatch.setattr(login, "new_mp_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    res = await login.poll_status(db_session, "sess-2", uuid.uuid4())
    assert res["status"] == "waiting"


@pytest.mark.asyncio
async def test_poll_bizlogin_failure_persists_nothing(db_session, monkeypatch):
    from app.social.wechat import login, session_store

    async def fake_load(sid):
        return "uuid=UU"
    monkeypatch.setattr(session_store, "load", fake_load)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "scanloginqrcode" in url and "action=ask" in url:
            return httpx.Response(200, json={"status": 1, "acct_size": 1, "base_resp": {"ret": 0}})
        if "bizlogin" in url:
            return httpx.Response(200, json={"base_resp": {"ret": 200013, "err_msg": "freq"}})
        return httpx.Response(200, json={"base_resp": {"ret": 0}})

    monkeypatch.setattr(login, "new_mp_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    from app.core.security import hash_password
    user_id = uuid.uuid4()
    u = User(id=user_id, email=f"login-{user_id.hex[:6]}@t.dev", password_hash=hash_password("x"))
    db_session.add(u)
    await db_session.commit()

    res = await login.poll_status(db_session, "sess-3", user_id)
    assert res["status"] == "failed"

    cred = await db_session.scalar(select(WechatCredential).where(WechatCredential.user_id == user_id))
    assert cred is None
