import asyncio
import logging
import random

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.social.models import WeiboAccount, WeiboSubscription
from app.social.weibo import cooldown
from app.social.weibo.client import new_weibo_client
from app.social.weibo.credentials import mark_blocked, mark_expired, pick_credential
from app.social.weibo.errors import (
    InvalidWeiboPayloadError,
    WeiboRateLimitedError,
    WeiboSessionExpiredError,
    WeiboTransientError,
)
from app.social.weibo.ingest import ingest_account, mark_account_error

_log = logging.getLogger(__name__)


async def _gap() -> None:
    base = get_settings().weibo_poll_gap_seconds
    if base > 0:
        await asyncio.sleep(base * random.uniform(0.6, 1.4))


async def poll_all_subscriptions() -> int:
    """顺序同步启用账号；失效/风控中止整轮，账号级错误只隔离当前账号。"""
    if await cooldown.remaining() > 0:
        _log.info("weibo poll skipped: global cooldown active")
        return 0
    async with get_sessionmaker()() as db:
        credential = await pick_credential(db)
        if credential is None:
            _log.warning("weibo poll skipped: no active credential")
            return 0
        account_ids = (
            (
                await db.execute(
                    select(WeiboSubscription.account_id)
                    .where(WeiboSubscription.enabled.is_(True))
                    .distinct()
                    .limit(get_settings().weibo_max_accounts)
                )
            )
            .scalars()
            .all()
        )
        accounts = (
            (await db.execute(select(WeiboAccount).where(WeiboAccount.id.in_(account_ids))))
            .scalars()
            .all()
        )

    total = 0
    async with new_weibo_client(credential.cookies) as client:
        for index, account in enumerate(accounts):
            if index:
                await _gap()
            try:
                async with get_sessionmaker()() as db:
                    current = await db.get(WeiboAccount, account.id)
                    total += await ingest_account(db, current, credential, client)
            except WeiboSessionExpiredError as exc:
                async with get_sessionmaker()() as db:
                    await mark_expired(db, credential.id, str(exc))
                _log.warning("weibo poll stopped: session expired")
                break
            except WeiboRateLimitedError as exc:
                seconds = get_settings().weibo_global_cooldown_minutes * 60
                await cooldown.trip(seconds)
                async with get_sessionmaker()() as db:
                    await mark_blocked(db, credential.id, seconds, str(exc))
                _log.warning("weibo poll stopped: rate limited")
                break
            except (WeiboTransientError, InvalidWeiboPayloadError) as exc:
                async with get_sessionmaker()() as db:
                    await mark_account_error(db, account.id, str(exc))
                _log.warning("weibo poll skipped account %s: %s", account.id, exc)
            except Exception as exc:  # noqa: BLE001 — 单账号故障隔离
                async with get_sessionmaker()() as db:
                    await mark_account_error(db, account.id, "微博同步发生内部错误")
                _log.exception("weibo poll failed for account %s: %s", account.id, exc)
    return total
