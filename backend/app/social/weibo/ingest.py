import datetime as dt
import logging
import re
import uuid
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.social.models import WeiboAccount, WeiboPost
from app.social.weibo.client import WeiboClient, new_weibo_client
from app.social.weibo.credentials import ActiveWeiboCredential, verify_active
from app.social.weibo.errors import (
    InvalidWeiboPayloadError,
    InvalidWeiboProfileUrlError,
)
from app.social.weibo.parser import RawWeiboPost, WeiboProfile

_log = logging.getLogger(__name__)
_UID_PATH = re.compile(r"^/(?:u/)?([1-9]\d{4,19})/?$")
_ALLOWED_HOSTS = {"weibo.com", "www.weibo.com", "m.weibo.cn"}


def parse_profile_uid(profile_url: str) -> str:
    try:
        parsed = urlparse(profile_url.strip())
    except ValueError as exc:
        raise InvalidWeiboProfileUrlError("微博主页链接格式无效") from exc
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in _ALLOWED_HOSTS:
        raise InvalidWeiboProfileUrlError("仅支持 weibo.com 或 m.weibo.cn 的主页链接")
    match = _UID_PATH.fullmatch(parsed.path)
    if match is None or parsed.params:
        raise InvalidWeiboProfileUrlError("主页链接必须明确包含数字 UID")
    return match.group(1)


async def _save_profile(db: AsyncSession, profile: WeiboProfile) -> WeiboAccount:
    account_id = await db.scalar(
        insert(WeiboAccount)
        .values(
            uid=profile.uid,
            name=profile.name,
            avatar=profile.avatar,
            description=profile.description,
            profile_url=f"https://weibo.com/u/{profile.uid}",
            container_id=profile.container_id,
        )
        .on_conflict_do_update(
            index_elements=[WeiboAccount.uid],
            set_={
                "name": profile.name,
                "avatar": profile.avatar,
                "description": profile.description,
                "profile_url": f"https://weibo.com/u/{profile.uid}",
                "container_id": profile.container_id,
                "updated_at": func.now(),
            },
        )
        .returning(WeiboAccount.id)
    )
    await db.commit()
    return await db.get(WeiboAccount, account_id)


async def preview_account(db: AsyncSession, profile_url: str) -> WeiboAccount:
    uid = parse_profile_uid(profile_url)
    credential = await verify_active(db)
    async with new_weibo_client(credential.cookies) as client:
        profile = await client.get_profile(uid)
    return await _save_profile(db, profile)


def _choose_detail(summary: RawWeiboPost, detail: RawWeiboPost) -> RawWeiboPost:
    if detail.external_id != summary.external_id:
        return summary
    return detail


async def _ingest_with_client(
    db: AsyncSession,
    account: WeiboAccount,
    client: WeiboClient,
    *,
    initial: bool,
    commit: bool,
) -> int:
    settings = get_settings()
    maximum = settings.weibo_fetch_count
    added = 0
    stop = False
    for page in range(1, settings.weibo_max_pages + 1):
        summaries = await client.get_posts(account.uid, account.container_id, page)
        if not summaries:
            break
        for summary in summaries:
            if summary.is_repost:
                continue
            existing = await db.scalar(
                select(WeiboPost.id).where(
                    WeiboPost.account_id == account.id,
                    WeiboPost.external_id == summary.external_id,
                )
            )
            if existing is not None:
                # A known pinned status can be rendered before newer statuses on
                # every page. It is not the incremental boundary; stopping on it
                # would permanently hide all new posts listed below the pin.
                if not initial and not summary.is_pinned:
                    stop = True
                    break
                continue
            try:
                detail = _choose_detail(summary, await client.get_status(summary.bid))
            except InvalidWeiboPayloadError:
                _log.warning(
                    "weibo detail unavailable for %s; using list snapshot", summary.external_id
                )
                detail = summary
            if detail.is_repost:
                continue
            result = await db.execute(
                insert(WeiboPost)
                .values(
                    account_id=account.id,
                    external_id=detail.external_id,
                    bid=detail.bid,
                    content=detail.content,
                    url=f"https://weibo.com/{account.uid}/{detail.bid}",
                    media=detail.media,
                    published_at=detail.published_at,
                    captured_at=dt.datetime.now(dt.UTC),
                )
                .on_conflict_do_nothing(constraint="uq_weibo_account_external")
            )
            if result.rowcount:
                added += 1
            if added >= maximum:
                stop = True
                break
        if stop:
            break
    account.last_synced_at = dt.datetime.now(dt.UTC)
    account.last_sync_status = "ok"
    account.last_sync_error = None
    if commit:
        await db.commit()
    else:
        await db.flush()
    return added


async def mark_account_error(db: AsyncSession, account_id: uuid.UUID, message: str) -> None:
    # 同步可能已 flush 部分新快照；账号级失败必须整批回滚，不能提交半轮数据。
    await db.rollback()
    account = await db.get(WeiboAccount, account_id)
    if account is not None:
        account.last_sync_status = "error"
        account.last_sync_error = message[:1024]
        await db.commit()


async def ingest_account(
    db: AsyncSession,
    account: WeiboAccount,
    credential: ActiveWeiboCredential | None = None,
    client: WeiboClient | None = None,
    *,
    initial: bool = False,
    commit: bool = True,
) -> int:
    active = credential or await verify_active(db)
    if client is not None:
        return await _ingest_with_client(
            db,
            account,
            client,
            initial=initial,
            commit=commit,
        )
    async with new_weibo_client(active.cookies) as upstream:
        return await _ingest_with_client(
            db,
            account,
            upstream,
            initial=initial,
            commit=commit,
        )
