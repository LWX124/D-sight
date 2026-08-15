"""微信风控熔断 / 节流。

熔断状态真实存在 Redis。这里把 `cooldown` 模块的读写换成内存假实现，
既避免测试之间互相污染（真冷却默认 60 分钟），也避免 CI 依赖 Redis。
"""

import datetime as dt
import json
import uuid

import httpx
import pytest

from app.auth.models import User  # noqa: F401 — 注册 FK 目标表
from app.core.security import create_access_token
from app.social import crypto
from app.social.models import WechatAccount, WechatCredential, WechatSubscription
from app.social.wechat.client import ActiveCred, appmsg_publish
from app.social.wechat.errors import FreqControlError, TransientMpError, check_base_resp


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _make_admin(db_session, user) -> None:
    row = await db_session.get(User, user.id)
    row.role = "admin"
    await db_session.commit()


def _cooldown_seconds() -> int:
    from app.core.config import get_settings

    return get_settings().social_freq_cooldown_minutes * 60


def _active_cred_row(user_id) -> WechatCredential:
    return WechatCredential(
        user_id=user_id, token=crypto.encrypt("tok"), cookies=crypto.encrypt("ck"),
        nickname="号", status="active",
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=3),
    )


def _cred():
    return ActiveCred(id=uuid.uuid4(), token="tok", cookies="slave_sid=abc")


def _freq_handler(calls: list):
    """始终返回 freq control，并记录实际发出的请求。"""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"base_resp": {"ret": 200013, "err_msg": "freq control"}})

    return handler


class _FakeCooldown:
    """内存版熔断状态，接口与 app.social.wechat.cooldown 对齐。"""

    def __init__(self, initial: int = 0):
        self.left = initial
        self.tripped: list[int] = []
        self.refresh: dict[str, int] = {}
        self.released: list[str] = []

    async def remaining(self) -> int:
        return self.left

    async def trip(self, seconds: int) -> None:
        self.tripped.append(seconds)
        self.left = seconds

    async def clear(self) -> None:
        self.left = 0

    async def try_acquire_refresh(self, account_id: str, seconds: int) -> int:
        if account_id in self.refresh:
            return self.refresh[account_id]
        self.refresh[account_id] = seconds
        return 0

    async def release_refresh(self, account_id: str) -> None:
        self.refresh.pop(account_id, None)
        self.released.append(account_id)


@pytest.fixture
def fake_cooldown(monkeypatch):
    """安装内存熔断。调用方式：`fake = fake_cooldown()` 或 `fake_cooldown(initial=600)`。"""

    def _install(initial: int = 0) -> _FakeCooldown:
        fake = _FakeCooldown(initial)
        from app.social.wechat import cooldown as real

        for name in ("remaining", "trip", "clear", "try_acquire_refresh", "release_refresh"):
            monkeypatch.setattr(real, name, getattr(fake, name))
        return fake

    return _install


# ---- 错误分类 ----
def test_freq_control_is_transient_subclass():
    # 既有 `except TransientMpError` 路径必须仍然兜住 200013（凭证不能被标 expired）
    assert issubclass(FreqControlError, TransientMpError)


def test_check_base_resp_maps_200013():
    with pytest.raises(FreqControlError):
        check_base_resp({"base_resp": {"ret": 200013, "err_msg": "freq control"}})


def test_check_base_resp_other_ret_stays_plain_transient():
    with pytest.raises(TransientMpError) as ei:
        check_base_resp({"base_resp": {"ret": 200002, "err_msg": "invalid args"}})
    assert not isinstance(ei.value, FreqControlError)
    assert "200002" in str(ei.value)  # ret 码要能自解释，不能再谎称「限流」


# ---- 熔断写入与拦截 ----
@pytest.mark.asyncio
async def test_200013_trips_cooldown(fake_cooldown):
    fake = fake_cooldown()
    calls: list = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(_freq_handler(calls))) as http:
        with pytest.raises(FreqControlError) as ei:
            await appmsg_publish(http, _cred(), "F1")

    assert len(calls) == 1
    assert fake.tripped == [_cooldown_seconds()]
    assert ei.value.retry_after == _cooldown_seconds()


@pytest.mark.asyncio
async def test_cooldown_short_circuits_without_http(fake_cooldown):
    fake_cooldown(initial=1234)
    calls: list = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(_freq_handler(calls))) as http:
        with pytest.raises(FreqControlError) as ei:
            await appmsg_publish(http, _cred(), "F1")

    assert calls == []  # 关键：冷却期内一个真实请求都不能发
    assert ei.value.retry_after == 1234


# ---- 轮询节流 / 中止 ----
@pytest.mark.asyncio
async def test_gap_sleeps_with_jitter(monkeypatch):
    from app.core.config import Settings, get_settings
    from app.social import job

    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    monkeypatch.setattr(job.asyncio, "sleep", fake_sleep)
    patched = Settings(**{**get_settings().model_dump(), "social_poll_gap_seconds": 5.0})
    monkeypatch.setattr("app.core.config.get_settings", lambda: patched)

    await job._gap()
    assert len(slept) == 1
    assert 3.0 <= slept[0] <= 7.0  # 5s ±40%


@pytest.mark.asyncio
async def test_gap_disabled_does_not_sleep(monkeypatch):
    from app.social import job

    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    monkeypatch.setattr(job.asyncio, "sleep", fake_sleep)
    await job._gap()  # conftest 已把 SOCIAL_POLL_GAP_SECONDS 设为 0
    assert slept == []


@pytest.mark.asyncio
async def test_poll_aborts_on_freq_control(db_session, monkeypatch, fake_cooldown):
    """命中风控当轮必须 break：继续遍历只会给封禁窗口续期，且凭证不能被标 expired。"""
    from app.core.security import hash_password
    from app.social import job
    from app.social.ingest import get_or_create_account

    fake = fake_cooldown()
    u = User(email=f"freq-{uuid.uuid4().hex[:6]}@t.dev", password_hash=hash_password("x"))
    db_session.add(u)
    await db_session.flush()
    cred_row = _active_cred_row(u.id)
    db_session.add(cred_row)
    accs = [await get_or_create_account(db_session, f"F{uuid.uuid4().hex[:8]}", f"号{i}") for i in range(3)]
    for a in accs:
        db_session.add(WechatSubscription(user_id=u.id, account_id=a.id, enabled=True))
    await db_session.commit()

    calls: list = []

    async def fake_pick(db):
        return _cred()

    monkeypatch.setattr(job, "pick_credential", fake_pick)
    monkeypatch.setattr(
        job, "new_mp_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_freq_handler(calls))),
    )

    added = await job.poll_all_subscriptions()

    assert added == 0
    assert len(calls) == 1  # 第一个号就撞墙，剩下的不再打
    assert fake.tripped == [_cooldown_seconds()]
    await db_session.refresh(cred_row)
    assert cred_row.status == "active"  # 风控不得烧掉凭证


# ---- API 层 ----
@pytest.mark.asyncio
async def test_refresh_returns_429_when_cooling_down(client, db_session, registered_user, fake_cooldown):
    await _make_admin(db_session, registered_user)
    fake_cooldown(initial=900)
    acc = WechatAccount(fakeid=f"C{uuid.uuid4().hex[:6]}", name="冷却号")
    db_session.add(acc)
    await db_session.commit()

    r = await client.post(
        f"/api/social/wechat/refresh?account_id={acc.id}", headers=_auth(registered_user)
    )
    assert r.status_code == 429
    assert r.headers["retry-after"] == "900"
    assert "15 分钟" in r.json()["detail"]


@pytest.mark.asyncio
async def test_refresh_per_account_cooldown(client, db_session, registered_user, monkeypatch, fake_cooldown):
    """同账号连点第二次直接被挡，不产生真实微信请求。"""
    await _make_admin(db_session, registered_user)
    fake_cooldown()
    acc = WechatAccount(fakeid=f"D{uuid.uuid4().hex[:6]}", name="连点号")
    db_session.add(acc)
    db_session.add(_active_cred_row(registered_user.id))
    await db_session.commit()

    calls: list = []

    def ok_handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        page = json.dumps({"publish_list": [{"publish_info": json.dumps({"appmsgex": []})}]})
        return httpx.Response(200, json={"base_resp": {"ret": 0}, "publish_page": page})

    from app.social import router as social_router

    monkeypatch.setattr(
        social_router, "new_mp_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(ok_handler)),
    )

    h = _auth(registered_user)
    url = f"/api/social/wechat/refresh?account_id={acc.id}"
    r1 = await client.post(url, headers=h)
    assert r1.status_code == 200
    r2 = await client.post(url, headers=h)
    assert r2.status_code == 429
    assert len(calls) == 1  # 第二次没有打微信


@pytest.mark.asyncio
async def test_refresh_other_ret_reports_real_code(client, db_session, registered_user, monkeypatch, fake_cooldown):
    await _make_admin(db_session, registered_user)
    fake_cooldown()
    acc = WechatAccount(fakeid=f"E{uuid.uuid4().hex[:6]}", name="错误号")
    db_session.add(acc)
    db_session.add(_active_cred_row(registered_user.id))
    await db_session.commit()

    from app.social import router as social_router

    monkeypatch.setattr(
        social_router, "new_mp_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"base_resp": {"ret": 200002, "err_msg": "invalid args"}})
        )),
    )

    r = await client.post(
        f"/api/social/wechat/refresh?account_id={acc.id}", headers=_auth(registered_user)
    )
    assert r.status_code == 503
    assert "200002" in r.json()["detail"]  # 不再是含糊的「限流」


@pytest.mark.asyncio
async def test_cooldown_helpers_fail_open_without_redis(monkeypatch):
    """Redis 挂了要放行，不能让熔断模块把整个功能拖死。"""
    from app.social.wechat import cooldown

    class _Dead:
        def __getattr__(self, _name):
            async def boom(*a, **kw):
                raise ConnectionError("redis down")

            return boom

    monkeypatch.setattr(cooldown, "_redis", lambda: _Dead())
    assert await cooldown.remaining() == 0
    assert await cooldown.try_acquire_refresh("acc", 60) == 0
    await cooldown.trip(60)  # 不抛
    await cooldown.release_refresh("acc")
    await cooldown.clear()
