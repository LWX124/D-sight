import uuid

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.db import get_db
from app.core.security import decode_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if cred is None:
        raise HTTPException(401, "未登录")
    try:
        payload = decode_token(cred.credentials)
    except jwt.InvalidTokenError:
        raise HTTPException(401, "登录状态无效，请重新登录")
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise HTTPException(401, "用户不存在")
    return user
