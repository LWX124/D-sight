import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.auth.models import User
from app.core.security import create_access_token
from tests.test_auth_api import _register


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


@pytest.fixture
async def registered_user(client, db_session):
    email = f"credits-user-{uuid.uuid4().hex[:8]}@test.dev"
    await _register(client, db_session, email)
    row = await db_session.scalar(select(User).where(User.email == email))
    return SimpleNamespace(id=row.id, email=email)


@pytest.mark.asyncio
async def test_get_credits_returns_balance(client, registered_user):
    resp = await client.get("/api/credits", headers=_auth(registered_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["balance"] == 100 and body["monthly_quota"] == 100 and body["plan"] == "free"
