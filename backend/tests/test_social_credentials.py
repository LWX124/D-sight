import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from app.auth.models import User  # noqa: F401  # register users table for FK resolution
from app.social import crypto
from app.social.models import WechatCredential


def _cred(status="active", days=1, tok="T"):
    return WechatCredential(
        user_id=None, token=crypto.encrypt(tok), cookies=crypto.encrypt("c"),
        nickname="n", expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=days), status=status,
    )


@pytest.mark.asyncio
async def test_pick_returns_active_decrypted(db_session):
    c = _cred(tok="TOKACT")
    db_session.add(c)
    await db_session.commit()
    from app.social.credentials import pick_credential

    got = await pick_credential(db_session)
    assert got is not None
    assert got.token == "TOKACT"


@pytest.mark.asyncio
async def test_pick_skips_and_marks_time_expired(db_session):
    from sqlalchemy import update
    # 清场：把此前用例遗留的 active 凭证全标 expired，隔离本用例
    await db_session.execute(update(WechatCredential).values(status="expired"))
    await db_session.commit()
    stale = _cred(days=-1, tok="OLD")
    db_session.add(stale)
    await db_session.commit()
    from app.social.credentials import pick_credential

    got = await pick_credential(db_session)
    assert got is None
    row = await db_session.scalar(select(WechatCredential).where(WechatCredential.id == stale.id))
    assert row.status == "expired"


@pytest.mark.asyncio
async def test_pick_skips_undecryptable_credential(db_session):
    from sqlalchemy import update

    # 清场：把此前用例遗留的 active 凭证全标 expired，隔离本用例
    await db_session.execute(update(WechatCredential).values(status="expired"))
    await db_session.commit()

    broken = WechatCredential(
        user_id=None, token="not-a-valid-fernet-token", cookies="x",
        nickname="broken", expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=1), status="active",
    )
    db_session.add(broken)
    await db_session.commit()

    good = _cred(tok="GOODTOK")
    db_session.add(good)
    await db_session.commit()

    # 强制损坏那条排在最前（pick_credential 按 updated_at desc 排序）
    await db_session.execute(
        update(WechatCredential).where(WechatCredential.id == broken.id)
        .values(updated_at=dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10))
    )
    await db_session.commit()

    from app.social.credentials import pick_credential

    got = await pick_credential(db_session)
    assert got is not None
    assert got.token == "GOODTOK"

    row = await db_session.scalar(select(WechatCredential).where(WechatCredential.id == broken.id))
    assert row.status == "expired"


@pytest.mark.asyncio
async def test_mark_expired(db_session):
    c = _cred()
    db_session.add(c)
    await db_session.commit()
    from app.social.credentials import mark_expired

    await mark_expired(db_session, c.id)
    row = await db_session.scalar(select(WechatCredential).where(WechatCredential.id == c.id))
    assert row.status == "expired"
