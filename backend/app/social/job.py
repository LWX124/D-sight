import logging

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.social.credentials import mark_expired, pick_credential
from app.social.ingest import ingest_account
from app.social.models import WechatAccount, WechatSubscription
from app.social.wechat.client import new_mp_client
from app.social.wechat.errors import SessionExpiredError, TransientMpError

_log = logging.getLogger(__name__)


async def poll_all_subscriptions() -> int:
    """遍历 enabled 订阅去重后的号，用池凭证增量抓取。池空则整轮跳过。"""
    async with get_sessionmaker()() as db:
        account_ids = (await db.execute(
            select(WechatSubscription.account_id).where(WechatSubscription.enabled.is_(True)).distinct()
        )).scalars().all()
        if not account_ids:
            return 0
        cred = await pick_credential(db)
        if cred is None:
            _log.warning("social poll skipped: 凭证池为空")
            return 0
        accounts = (await db.execute(
            select(WechatAccount).where(WechatAccount.id.in_(account_ids))
        )).scalars().all()

    total = 0
    async with new_mp_client() as http:
        for account in accounts:
            try:
                async with get_sessionmaker()() as db:
                    acc = await db.get(WechatAccount, account.id)
                    total += await ingest_account(db, acc, cred, http)
            except SessionExpiredError:
                async with get_sessionmaker()() as db:
                    await mark_expired(db, cred.id)
                _log.warning("social poll: 凭证失效，本轮中止")
                break
            except TransientMpError:
                _log.warning("social poll: 临时错误，跳过 %s", account.id)
            except Exception:  # noqa: BLE001 — 单号失败隔离
                _log.exception("social poll failed for account %s", account.id)
    return total
