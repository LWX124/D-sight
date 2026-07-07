import datetime as dt
import uuid

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    # 防御深度：bcrypt 对 >72 字节密码抛 ValueError，此处兜底返回 False（登录返回 401 而非 500）。
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(user_id: str) -> str:
    s = get_settings()
    now = dt.datetime.now(dt.UTC)
    payload = {
        "sub": user_id,
        "type": "access",
        "iat": now,
        "exp": now + dt.timedelta(minutes=s.access_token_ttl_min),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def create_refresh_token(user_id: str) -> tuple[str, str, dt.datetime]:
    """返回 (token, jti, expires_at)；jti 由调用方入库用于吊销。"""
    s = get_settings()
    now = dt.datetime.now(dt.UTC)
    jti = uuid.uuid4().hex
    expires = now + dt.timedelta(days=s.refresh_token_ttl_days)
    payload = {"sub": user_id, "type": "refresh", "jti": jti, "iat": now, "exp": expires}
    return jwt.encode(payload, s.jwt_refresh_secret, algorithm="HS256"), jti, expires


def decode_token(token: str, *, refresh: bool = False) -> dict:
    s = get_settings()
    secret = s.jwt_refresh_secret if refresh else s.jwt_secret
    payload = jwt.decode(token, secret, algorithms=["HS256"])
    expected = "refresh" if refresh else "access"
    if payload.get("type") != expected:
        raise jwt.InvalidTokenError(f"token type 应为 {expected}")
    return payload
