from fastapi import Depends, HTTPException

from app.auth.deps import get_current_user
from app.auth.models import User


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user
