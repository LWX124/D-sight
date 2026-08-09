import datetime as dt
import uuid

import pytest

from app.auth.models import User
from app.core.db import get_sessionmaker
from app.core.security import hash_password
from app.social.models import WeiboAccount, WeiboPost, WeiboSubscription


@pytest.mark.asyncio
async def test_weibo_query_filters_and_isolates_users(db_session):
    owner = User(email=f"weibo-owner-{uuid.uuid4().hex}@t.dev", password_hash=hash_password("x"))
    stranger = User(email=f"weibo-other-{uuid.uuid4().hex}@t.dev", password_hash=hash_password("x"))
    account = WeiboAccount(
        uid=f"7{uuid.uuid4().int % 10**10:010d}",
        name="投研账号",
        profile_url="https://weibo.com/u/7",
        container_id="1076037",
    )
    db_session.add_all([owner, stranger, account])
    await db_session.flush()
    db_session.add_all(
        [
            WeiboSubscription(user_id=owner.id, account_id=account.id, enabled=True),
            WeiboPost(
                account_id=account.id,
                external_id=uuid.uuid4().hex,
                bid="B1",
                content="茅台估值分析",
                url="https://weibo.com/7/B1",
                media=[],
                published_at=dt.datetime.now(dt.UTC),
                captured_at=dt.datetime.now(dt.UTC),
            ),
        ]
    )
    await db_session.commit()

    from app.agent.tools.social import make_weibo_query

    owner_tool = make_weibo_query(get_sessionmaker(), owner.id)
    assert "茅台估值分析" in await owner_tool.ainvoke(
        {"account": "投研", "keyword": "茅台", "days": 30, "limit": 5}
    )
    stranger_tool = make_weibo_query(get_sessionmaker(), stranger.id)
    assert "无相关" in await stranger_tool.ainvoke({"keyword": "茅台"})
