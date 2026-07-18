import uuid

import httpx
import pytest
from sqlalchemy import select

from app.auth.models import User  # noqa: F401 — 注册 users 表以解析 FK
from app.social.models import WechatCredential


@pytest.mark.asyncio
async def test_start_qrcode_does_startlogin_before_getqrcode(monkeypatch):
    """微信要求先 bizlogin?action=startlogin 建会话，getqrcode 才返回图片；否则空 body。"""
    from app.social.wechat import login, session_store

    saved: dict = {}

    async def fake_save(sid, cookies):
        saved["sid"] = sid
        saved["cookies"] = cookies

    monkeypatch.setattr(session_store, "save", fake_save)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "bizlogin" in url and request.url.params.get("action") == "startlogin":
            return httpx.Response(
                200,
                json={"base_resp": {"ret": 0, "err_msg": "ok"}, "uuid": "UU1"},
                headers={"set-cookie": "uuid=UU1; Path=/; Secure; HttpOnly"},
            )
        if "scanloginqrcode" in url and "action=getqrcode" in url:
            if "uuid=UU1" not in request.headers.get("cookie", ""):
                return httpx.Response(200, content=b"")  # 微信真实行为：无会话时 200 空 body
            return httpx.Response(200, content=b"\xff\xd8JPEG", headers={"content-type": "image/jpg"})
        return httpx.Response(404)

    monkeypatch.setattr(login, "new_mp_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    session_id, mime, img = await login.start_qrcode()
    assert img.startswith(b"\xff\xd8")
    assert mime == "image/jpg"
    assert saved["sid"] == session_id
    assert "uuid=UU1" in saved["cookies"]


@pytest.mark.asyncio
async def test_start_qrcode_empty_image_raises(monkeypatch):
    """二维码接口返回空 body（被限流/会话未建立）时应报错，而不是返回空图。"""
    from app.social.wechat import login, session_store
    from app.social.wechat.errors import TransientMpError

    async def fake_save(sid, cookies):
        return None

    monkeypatch.setattr(session_store, "save", fake_save)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "bizlogin" in url:
            return httpx.Response(200, json={"base_resp": {"ret": 0}})
        return httpx.Response(200, content=b"")

    monkeypatch.setattr(login, "new_mp_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    with pytest.raises(TransientMpError):
        await login.start_qrcode()


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
        if "cgi-bin/home" in url:
            html = 'wx.cgiData.nick_name = "我的号";\nwx.cgiData.head_img = "http://a";'
            return httpx.Response(200, text=html)
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
@pytest.mark.parametrize(
    ("ask_json", "expected"),
    [
        ({"status": 0, "base_resp": {"ret": 0}}, "waiting"),
        ({"status": 2, "base_resp": {"ret": 0}}, "expired"),   # 二维码已失效
        ({"status": 3, "base_resp": {"ret": 0}}, "expired"),
        ({"status": 4, "acct_size": 1, "base_resp": {"ret": 0}}, "scanned"),
        ({"status": 6, "acct_size": 2, "base_resp": {"ret": 0}}, "scanned"),
        ({"status": 4, "acct_size": 0, "base_resp": {"ret": 0}}, "no_account"),  # 扫码微信无公众号
        ({"status": 5, "base_resp": {"ret": 0}}, "no_email"),  # 未绑定邮箱
    ],
)
async def test_poll_maps_all_wechat_statuses(db_session, monkeypatch, ask_json, expected):
    """微信 ask 的每种状态都必须映射为前端可感知的状态，不允许静默吞掉。"""
    from app.social.wechat import login, session_store

    async def fake_load(sid):
        return "uuid=UU"
    monkeypatch.setattr(session_store, "load", fake_load)

    def handler(request):
        return httpx.Response(200, json=ask_json)
    monkeypatch.setattr(login, "new_mp_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    res = await login.poll_status(db_session, "sess-s", uuid.uuid4())
    assert res["status"] == expected


@pytest.mark.asyncio
async def test_poll_confirmed_bizlogin_sends_reference_fields(db_session, monkeypatch):
    """bizlogin?action=login 需带 cookie_forbidden/cookie_cleaned/plugin_used（对齐参考实现）。"""
    from app.social.wechat import login, session_store

    async def fake_load(sid):
        return "uuid=UU"
    async def fake_delete(sid):
        return None
    monkeypatch.setattr(session_store, "load", fake_load)
    monkeypatch.setattr(session_store, "delete", fake_delete)

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "scanloginqrcode" in url and "action=ask" in url:
            return httpx.Response(200, json={"status": 1, "acct_size": 1, "base_resp": {"ret": 0}})
        if "bizlogin" in url:
            seen["body"] = request.content.decode()
            return httpx.Response(
                200,
                json={"base_resp": {"ret": 0}, "redirect_url": "/cgi-bin/home?token=TK9"},
                headers={"set-cookie": "slave_sid=SS; Path=/"},
            )
        return httpx.Response(200, json={"base_resp": {"ret": 0}, "nick_name": "N"})

    monkeypatch.setattr(login, "new_mp_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    from app.core.security import hash_password
    user_id = uuid.uuid4()
    u = User(id=user_id, email=f"login-{user_id.hex[:6]}@t.dev", password_hash=hash_password("x"))
    db_session.add(u)
    await db_session.commit()

    res = await login.poll_status(db_session, "sess-f", user_id)
    assert res["status"] == "confirmed"
    for field in ("cookie_forbidden=0", "cookie_cleaned=0", "plugin_used=0"):
        assert field in seen["body"]


@pytest.mark.asyncio
async def test_poll_confirmed_even_if_info_fetch_fails(db_session, monkeypatch):
    """昵称抓取只是展示信息：home 页返回空/非 HTML 也必须落库凭证并返回 confirmed。

    回归测试：曾因 /cgi-bin/info 返回空 body 抛 JSONDecodeError，把已成功的登录整个炸掉。
    """
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
                json={"base_resp": {"ret": 0}, "redirect_url": "/cgi-bin/home?token=TK77"},
                headers={"set-cookie": "slave_sid=SS; Path=/"},
            )
        return httpx.Response(200, content=b"")  # home 页空 body

    monkeypatch.setattr(login, "new_mp_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    from app.core.security import hash_password
    user_id = uuid.uuid4()
    u = User(id=user_id, email=f"login-{user_id.hex[:6]}@t.dev", password_hash=hash_password("x"))
    db_session.add(u)
    await db_session.commit()

    res = await login.poll_status(db_session, "sess-i", user_id)
    assert res["status"] == "confirmed"
    assert res["nickname"] == "公众号"  # 兜底昵称

    cred = await db_session.scalar(select(WechatCredential).where(WechatCredential.user_id == user_id))
    assert cred is not None
    assert crypto.decrypt(cred.token) == "TK77"


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
