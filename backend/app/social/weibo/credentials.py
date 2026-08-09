import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.social.crypto import decrypt, encrypt
from app.social.models import WeiboCredential
from app.social.weibo.client import new_weibo_client
from app.social.weibo.errors import WeiboSessionExpiredError

_MAX_COOKIE_BYTES = 16 * 1024


@dataclass(frozen=True)
class ActiveWeiboCredential:
    id: uuid.UUID
    cookies: str


def validate_cookies(cookies: str) -> str:
    value = cookies.strip()
    if not value:
        raise ValueError("Cookie 不能为空")
    if "\r" in value or "\n" in value:
        raise ValueError("Cookie 不能包含换行符")
    if len(value.encode()) > _MAX_COOKIE_BYTES:
        raise ValueError("Cookie 不能超过 16 KiB")
    return value


async def pick_credential(db: AsyncSession) -> ActiveWeiboCredential | None:
    now = dt.datetime.now(dt.UTC)
    stale_blocked = await db.scalar(
        select(WeiboCredential)
        .where(
            WeiboCredential.status == "blocked",
            WeiboCredential.blocked_until <= now,
        )
        .order_by(WeiboCredential.created_at.desc())
        .limit(1)
    )
    if stale_blocked is not None:
        stale_blocked.status = "active"
        stale_blocked.blocked_until = None
        stale_blocked.last_error = None
        await db.commit()
    row = await db.scalar(
        select(WeiboCredential)
        .where(WeiboCredential.status == "active")
        .order_by(WeiboCredential.created_at.desc())
        .limit(1)
    )
    if row is None:
        return None
    try:
        cookies = decrypt(row.cookies)
    except Exception:  # noqa: BLE001 — 密钥变更或密文损坏都视为凭证失效
        row.status = "expired"
        row.last_error = "凭证无法解密，请重新配置"
        await db.commit()
        return None
    return ActiveWeiboCredential(id=row.id, cookies=cookies)


async def replace_credential(db: AsyncSession, user_id: uuid.UUID, cookies: str) -> WeiboCredential:
    value = validate_cookies(cookies)
    async with new_weibo_client(value) as client:
        uid, nickname, avatar = await client.verify()
    now = dt.datetime.now(dt.UTC)
    # 全实例只有一个专用凭证；锁住替换窗口，避免并发写出两个 active 行。
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 867427})
    await db.execute(
        update(WeiboCredential)
        .where(WeiboCredential.status.in_(["active", "blocked"]))
        .values(status="expired", blocked_until=None)
    )
    row = WeiboCredential(
        user_id=user_id,
        cookies=encrypt(value),
        weibo_uid=uid,
        nickname=nickname,
        avatar=avatar,
        status="active",
        last_verified_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def mark_expired(
    db: AsyncSession, credential_id: uuid.UUID, message: str = "微博登录态已失效"
) -> None:
    row = await db.get(WeiboCredential, credential_id)
    if row is not None:
        row.status = "expired"
        row.blocked_until = None
        row.last_error = message[:1024]
        await db.commit()


async def mark_blocked(
    db: AsyncSession, credential_id: uuid.UUID, seconds: int, message: str
) -> None:
    row = await db.get(WeiboCredential, credential_id)
    if row is not None:
        row.status = "blocked"
        row.blocked_until = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=seconds)
        row.last_error = message[:1024]
        await db.commit()


async def disable_credential(db: AsyncSession) -> None:
    row = await db.scalar(
        select(WeiboCredential)
        .where(WeiboCredential.status.in_(["active", "blocked"]))
        .order_by(WeiboCredential.created_at.desc())
        .limit(1)
    )
    if row is not None:
        row.status = "expired"
        row.blocked_until = None
        row.last_error = "管理员已移除微博凭证"
        await db.commit()


async def verify_active(db: AsyncSession) -> ActiveWeiboCredential:
    credential = await pick_credential(db)
    if credential is None:
        raise WeiboSessionExpiredError("未配置有效微博 Cookie")
    return credential
