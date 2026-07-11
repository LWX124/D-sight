import datetime as dt

import pytest

from app.auth.models import User  # noqa: F401  # register users table for FK resolution
from app.social.models import (
    WechatAccount,
    WechatArticle,
    WechatCredential,
    WechatSubscription,
)


@pytest.mark.asyncio
async def test_create_account_article_credential(db_session):
    acc = WechatAccount(fakeid="fake1", name="某公众号")
    db_session.add(acc)
    await db_session.flush()

    art = WechatArticle(
        account_id=acc.id, external_id="aid1", title="标题", url="https://mp/s/x",
        published_at=dt.datetime(2026, 7, 10, tzinfo=dt.UTC),
    )
    db_session.add(art)

    cred = WechatCredential(
        user_id=None, token="enc-t", cookies="enc-c", nickname="我的号",
        expires_at=dt.datetime(2026, 7, 14, tzinfo=dt.UTC), status="active",
    )
    db_session.add(cred)
    await db_session.commit()

    assert art.content is None  # 懒抓，初始空
    assert cred.status == "active"
