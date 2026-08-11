"""深度分析测试公共 fixture。

与 conftest.py 复用同一 session-scoped DB，每个测试用唯一 user+ticker 避免唯一约束冲突。
"""
import uuid
from types import SimpleNamespace

import pytest

from app.auth.models import User
from app.core.security import create_access_token, hash_password
from app.credits.models import CreditAccount


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _mk_user(db, balance: int = 200, role: str = "user") -> User:
    """直接建用户+账户，不走注册流（避免邮箱限流），用于 service/worker 测试。

    注意：db 可能是 db_session fixture（已有隐式事务），也可能是独立 session。
    用 begin() 包裹会与 db_session 冲突，所以只 add + commit。
    """
    u = User(
        email=f"da-{uuid.uuid4().hex[:10]}@t.dev",
        password_hash=hash_password("pw-123456"),
        role=role,
    )
    db.add(u)
    await db.flush()
    acct = CreditAccount(
        user_id=u.id, balance=balance, monthly_quota=balance, plan="free"
    )
    db.add(acct)
    await db.commit()
    return u


@pytest.fixture
async def da_user(db_session):
    """带 200 积分的普通用户。"""
    u = await _mk_user(db_session, balance=200)
    yield SimpleNamespace(id=u.id, headers=_auth_simple(u))


def _auth_simple(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


@pytest.fixture
async def da_admin_user(db_session):
    """管理员用户，免扣费。"""
    u = await _mk_user(db_session, balance=0, role="admin")
    yield SimpleNamespace(id=u.id, headers=_auth_simple(u))


@pytest.fixture
async def da_poor_user(db_session):
    """余额不足的用户（10 积分）。"""
    u = await _mk_user(db_session, balance=10)
    yield SimpleNamespace(id=u.id, headers=_auth_simple(u))
