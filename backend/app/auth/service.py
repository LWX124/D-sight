import datetime as dt
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.emailer import get_email_sender
from app.auth.models import User, UserIdentity, VerificationCode
from app.core.security import hash_password, verify_password

CODE_TTL_MIN = 10
RESEND_INTERVAL_S = 60


class AuthError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def request_code(db: AsyncSession, email: str) -> str:
    latest = await db.scalar(
        select(VerificationCode)
        .where(VerificationCode.email == email)
        .order_by(VerificationCode.created_at.desc())
        .limit(1)
    )
    if latest and (_now() - latest.created_at).total_seconds() < RESEND_INTERVAL_S:
        raise AuthError(429, "验证码请求过于频繁，请 60 秒后再试")
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(
        VerificationCode(
            email=email, code=code, expires_at=_now() + dt.timedelta(minutes=CODE_TTL_MIN)
        )
    )
    await db.commit()
    await get_email_sender().send(
        email, "D-sight 注册验证码", f"验证码：{code}，{CODE_TTL_MIN} 分钟内有效"
    )
    return code


async def register(db: AsyncSession, email: str, code: str, password: str) -> User:
    if await db.scalar(select(User).where(User.email == email)):
        raise AuthError(409, "该邮箱已注册")
    vc = await db.scalar(
        select(VerificationCode)
        .where(
            VerificationCode.email == email,
            VerificationCode.code == code,
            VerificationCode.purpose == "register",
            VerificationCode.consumed_at.is_(None),
        )
        .order_by(VerificationCode.created_at.desc())
        .limit(1)
    )
    if vc is None or vc.expires_at < _now():
        # 错一次即作废该邮箱当前有效验证码，防止无限尝试爆破——需重新请求。
        latest = await db.scalar(
            select(VerificationCode)
            .where(
                VerificationCode.email == email,
                VerificationCode.purpose == "register",
                VerificationCode.consumed_at.is_(None),
            )
            .order_by(VerificationCode.created_at.desc())
            .limit(1)
        )
        if latest is not None:
            latest.consumed_at = _now()
            await db.commit()
        raise AuthError(400, "验证码错误或已过期")
    vc.consumed_at = _now()
    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    await db.flush()
    db.add(UserIdentity(user_id=user.id, provider="email", provider_uid=email))
    from app.credits.service import ensure_account
    from app.skills.seed import install_defaults

    await ensure_account(db, user.id)
    await install_defaults(db, user.id)
    try:
        await db.commit()
    except IntegrityError:
        # 并发重复注册：唯一约束冲突 → 409 而非 500。
        await db.rollback()
        raise AuthError(409, "该邮箱已注册")
    await db.refresh(user)
    return user


async def login(db: AsyncSession, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(password, user.password_hash):
        raise AuthError(401, "邮箱或密码错误")
    return user
