import datetime as dt
import uuid

import pytest
from sqlalchemy import func, select

from app.social.models import WeiboAccount, WeiboPost
from app.social.weibo.credentials import ActiveWeiboCredential
from app.social.weibo.errors import InvalidWeiboProfileUrlError
from app.social.weibo.ingest import ingest_account, parse_profile_uid
from app.social.weibo.parser import RawWeiboPost


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.details = 0

    async def get_posts(self, uid, container_id, page):
        return self.rows if page == 1 else []

    async def get_status(self, bid):
        self.details += 1
        return next(row for row in self.rows if row.bid == bid)


def _post(index: int, repost: bool = False, pinned: bool = False) -> RawWeiboPost:
    return RawWeiboPost(
        external_id=f"post-{index}",
        bid=f"B{index}",
        content=f"正文 {index}",
        published_at=dt.datetime(2026, 8, 6, index % 23, tzinfo=dt.UTC),
        media=[],
        is_repost=repost,
        is_pinned=pinned,
    )


def test_profile_url_accepts_only_explicit_numeric_uid():
    assert parse_profile_uid("https://weibo.com/u/123456") == "123456"
    assert parse_profile_uid("https://m.weibo.cn/u/123456/") == "123456"
    assert parse_profile_uid("https://weibo.com/u/123456?refer_flag=share") == "123456"
    with pytest.raises(InvalidWeiboProfileUrlError):
        parse_profile_uid("https://weibo.com/a-nickname")
    with pytest.raises(InvalidWeiboProfileUrlError):
        parse_profile_uid("https://evil.test/u/123456")


@pytest.mark.asyncio
async def test_initial_ingest_caps_originals_and_preserves_snapshot(db_session, monkeypatch):
    from app.core import config

    monkeypatch.setenv("WEIBO_FETCH_COUNT", "20")
    config.get_settings.cache_clear()
    account = WeiboAccount(
        uid=f"9{uuid.uuid4().int % 10**10:010d}",
        name="账号",
        profile_url="https://weibo.com/u/1",
        container_id="1076031",
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    rows = [_post(i) for i in range(1, 24)] + [_post(24, repost=True)]
    client = FakeClient(rows)
    credential = ActiveWeiboCredential(uuid.uuid4(), "test=1")

    assert await ingest_account(db_session, account, credential, client, initial=True) == 20
    assert (
        await db_session.scalar(
            select(func.count()).select_from(WeiboPost).where(WeiboPost.account_id == account.id)
        )
        == 20
    )
    saved = await db_session.scalar(select(WeiboPost).where(WeiboPost.external_id == "post-1"))
    saved_content = saved.content
    rows[0] = RawWeiboPost(**{**rows[0].__dict__, "content": "上游已编辑"})
    await ingest_account(db_session, account, credential, client, initial=False)
    await db_session.refresh(saved)
    assert saved.content == saved_content
    config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_incremental_ingest_does_not_stop_at_known_pinned_post(db_session):
    account = WeiboAccount(
        uid=f"2{uuid.uuid4().int % 10**10:010d}",
        name="置顶账号",
        profile_url="https://weibo.com/u/2",
        container_id="1076032",
    )
    db_session.add(account)
    await db_session.flush()
    known = _post(1, pinned=True)
    db_session.add(
        WeiboPost(
            account_id=account.id,
            external_id=known.external_id,
            bid=known.bid,
            content=known.content,
            url=f"https://weibo.com/{account.uid}/{known.bid}",
            media=[],
            published_at=known.published_at,
            captured_at=dt.datetime.now(dt.UTC),
        )
    )
    await db_session.commit()

    client = FakeClient([known, _post(2)])
    credential = ActiveWeiboCredential(uuid.uuid4(), "test=1")

    assert await ingest_account(db_session, account, credential, client, initial=False) == 1
    assert await db_session.scalar(
        select(func.count()).select_from(WeiboPost).where(WeiboPost.account_id == account.id)
    ) == 2
