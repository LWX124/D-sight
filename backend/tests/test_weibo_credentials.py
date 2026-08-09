import datetime as dt
import uuid
from contextlib import asynccontextmanager

import pytest

from app.auth.models import User
from app.core.security import hash_password
from app.social.crypto import decrypt, encrypt
from app.social.models import WeiboCredential


@pytest.mark.asyncio
async def test_replacing_credential_encrypts_cookie_and_expires_old(db_session, monkeypatch):
    from app.social.weibo import credentials

    admin = User(
        email=f"weibo-admin-{uuid.uuid4().hex}@t.dev",
        password_hash=hash_password("x"),
        role="admin",
    )
    db_session.add(admin)
    await db_session.flush()
    old = WeiboCredential(
        user_id=admin.id,
        cookies=encrypt("old=test-only"),
        status="active",
        last_verified_at=dt.datetime.now(dt.UTC),
    )
    db_session.add(old)
    await db_session.commit()

    class FakeClient:
        async def verify(self):
            return "123456", "专用账号", "https://img/avatar.jpg"

    @asynccontextmanager
    async def client(cookies):
        assert cookies == "SUB=test-only"
        yield FakeClient()

    monkeypatch.setattr(credentials, "new_weibo_client", client)
    row = await credentials.replace_credential(db_session, admin.id, "SUB=test-only")
    await db_session.refresh(old)
    assert old.status == "expired"
    assert row.cookies != "SUB=test-only"
    assert decrypt(row.cookies) == "SUB=test-only"
    assert row.nickname == "专用账号"


@pytest.mark.asyncio
async def test_undecryptable_cookie_is_marked_expired(db_session):
    from app.social.weibo.credentials import pick_credential

    admin = User(
        email=f"weibo-bad-{uuid.uuid4().hex}@t.dev",
        password_hash=hash_password("x"),
        role="admin",
    )
    db_session.add(admin)
    await db_session.flush()
    row = WeiboCredential(user_id=admin.id, cookies="not-fernet", status="active")
    db_session.add(row)
    await db_session.commit()
    assert await pick_credential(db_session) is None
    await db_session.refresh(row)
    assert row.status == "expired"
