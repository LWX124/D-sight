import datetime as dt
import uuid

from cryptography.fernet import InvalidToken
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.social import crypto
from app.social.models import WechatCredential
from app.social.wechat.client import ActiveCred


async def pick_credential(db: AsyncSession) -> ActiveCred | None:
    """挑一个 active 且未过期的凭证；顺手把时间已过的标 expired。池空返 None。"""
    now = dt.datetime.now(dt.UTC)
    rows = (await db.execute(
        select(WechatCredential)
        .where(WechatCredential.status == "active")
        .order_by(WechatCredential.updated_at.desc())
    )).scalars().all()
    for row in rows:
        if row.expires_at <= now:
            row.status = "expired"
            continue
        try:
            token = crypto.decrypt(row.token)
            cookies = crypto.decrypt(row.cookies)
        except InvalidToken:
            row.status = "expired"
            continue
        await db.commit()
        return ActiveCred(id=row.id, token=token, cookies=cookies)
    await db.commit()
    return None


async def mark_expired(db: AsyncSession, cred_id: uuid.UUID) -> None:
    await db.execute(
        update(WechatCredential).where(WechatCredential.id == cred_id).values(status="expired")
    )
    await db.commit()
