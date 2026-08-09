import datetime as dt
import uuid

import pytest
from sqlalchemy import delete, select

from app.auth.models import User
from app.core.security import create_access_token, hash_password
from app.social.models import WeiboAccount, WeiboPost, WeiboSubscription
from app.social.weibo.credentials import ActiveWeiboCredential
from app.social.weibo.errors import WeiboTransientError


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {user.token}"}


@pytest.mark.asyncio
async def test_regular_user_cannot_manage_credential(client, registered_user):
    response = await client.put(
        "/api/social/weibo/credential",
        json={"cookies": "test=not-real"},
        headers=_auth(registered_user),
    )
    assert response.status_code == 403
    status = await client.get("/api/social/weibo/credential", headers=_auth(registered_user))
    assert status.status_code == 200
    assert status.json()["can_manage"] is False
    assert "cookies" not in status.json()


@pytest.mark.asyncio
async def test_invalid_profile_url_is_422_without_upstream_call(client, registered_user):
    response = await client.post(
        "/api/social/weibo/accounts/preview",
        json={"profile_url": "https://weibo.com/a-name"},
        headers=_auth(registered_user),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_posts_are_isolated_by_user_subscription(client, registered_user, db_session):
    account = WeiboAccount(
        uid=f"8{uuid.uuid4().int % 10**10:010d}",
        name="隔离账号",
        profile_url="https://weibo.com/u/8",
        container_id="1076038",
    )
    db_session.add(account)
    await db_session.flush()
    post = WeiboPost(
        account_id=account.id,
        external_id=uuid.uuid4().hex,
        bid="B1",
        content="仅订阅用户可见",
        url="https://weibo.com/8/B1",
        media=[],
        published_at=dt.datetime.now(dt.UTC),
        captured_at=dt.datetime.now(dt.UTC),
    )
    db_session.add(post)
    await db_session.commit()

    denied = await client.get(
        f"/api/social/weibo/posts?account_id={account.id}", headers=_auth(registered_user)
    )
    assert denied.status_code == 403
    db_session.add(
        WeiboSubscription(user_id=registered_user.id, account_id=account.id, enabled=True)
    )
    await db_session.commit()
    allowed = await client.get(
        f"/api/social/weibo/posts?account_id={account.id}", headers=_auth(registered_user)
    )
    assert allowed.status_code == 200
    assert allowed.json()[0]["content"] == "仅订阅用户可见"


@pytest.mark.asyncio
async def test_instance_account_limit_returns_409(client, registered_user, db_session):
    accounts = [
        WeiboAccount(
            uid=f"4{index:010d}{uuid.uuid4().int % 1000:03d}",
            name=f"上限账号{index}",
            profile_url=f"https://weibo.com/u/{index}",
            container_id=f"1076034{index}",
        )
        for index in range(21)
    ]
    db_session.add_all(accounts)
    await db_session.flush()
    db_session.add_all(
        [
            WeiboSubscription(user_id=registered_user.id, account_id=account.id, enabled=True)
            for account in accounts[:20]
        ]
    )
    await db_session.commit()
    response = await client.post(
        "/api/social/weibo/subscriptions",
        json={"account_id": str(accounts[20].id)},
        headers=_auth(registered_user),
    )
    assert response.status_code == 409
    assert "20" in response.json()["detail"]


@pytest.mark.asyncio
async def test_failed_initial_sync_rolls_back_new_subscription(
    client, registered_user, db_session, monkeypatch
):
    from app.social.weibo import router

    # The suite intentionally keeps one PostgreSQL container for speed; remove
    # subscriptions created by the preceding global-limit test so this case
    # reaches the initial-sync transaction it is meant to exercise.
    await db_session.execute(delete(WeiboSubscription))
    await db_session.commit()
    account = WeiboAccount(
        uid=f"3{uuid.uuid4().int % 10**10:010d}",
        name="首次同步失败账号",
        profile_url="https://weibo.com/u/3",
        container_id="1076033",
    )
    db_session.add(account)
    await db_session.commit()

    async def active(db):
        return ActiveWeiboCredential(uuid.uuid4(), "test=1")

    async def fail_ingest(db, account, credential, *, initial=False):
        assert initial is True
        raise WeiboTransientError("temporary")

    async def no_cooldown():
        return 0

    monkeypatch.setattr(router, "_active_or_409", active)
    monkeypatch.setattr(router, "ingest_account", fail_ingest)
    monkeypatch.setattr(router.cooldown, "remaining", no_cooldown)

    response = await client.post(
        "/api/social/weibo/subscriptions",
        json={"account_id": str(account.id)},
        headers=_auth(registered_user),
    )

    assert response.status_code == 503
    subscription = await db_session.scalar(
        select(WeiboSubscription).where(
            WeiboSubscription.user_id == registered_user.id,
            WeiboSubscription.account_id == account.id,
        )
    )
    assert subscription is None


@pytest.mark.asyncio
async def test_admin_credential_response_never_echoes_cookie(client, db_session, monkeypatch):
    from app.social.weibo import router

    admin = User(
        email=f"weibo-api-admin-{uuid.uuid4().hex}@t.dev",
        password_hash=hash_password("x"),
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()

    async def replace(db, user_id, cookies):
        from app.social.models import WeiboCredential

        assert cookies == "SUB=test-only"
        return WeiboCredential(
            user_id=user_id,
            cookies="encrypted-value",
            weibo_uid="123456",
            nickname="专用账号",
            status="active",
            last_verified_at=dt.datetime.now(dt.UTC),
        )

    async def clear():
        return None

    monkeypatch.setattr(router, "replace_credential", replace)
    monkeypatch.setattr(router.cooldown, "clear", clear)
    response = await client.put(
        "/api/social/weibo/credential",
        json={"cookies": "SUB=test-only"},
        headers={"Authorization": f"Bearer {create_access_token(str(admin.id))}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "cookies" not in body
    assert "test-only" not in response.text


@pytest.mark.asyncio
async def test_oversized_admin_cookie_validation_never_echoes_input(client, db_session):
    admin = User(
        email=f"weibo-api-large-{uuid.uuid4().hex}@t.dev",
        password_hash=hash_password("x"),
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    secret_marker = "must-not-be-echoed"
    oversized = f"SUB={secret_marker};" + "x" * (16 * 1024)

    response = await client.put(
        "/api/social/weibo/credential",
        json={"cookies": oversized},
        headers={"Authorization": f"Bearer {create_access_token(str(admin.id))}"},
    )

    assert response.status_code == 422
    assert secret_marker not in response.text
