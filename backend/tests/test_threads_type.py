import pytest
from httpx import AsyncClient

from tests.test_auth_api import _register


async def _auth_headers(client, db_session, email: str) -> dict:
    token = await _register(client, db_session, email)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_threads_excludes_news_thread(client: AsyncClient, db_session):
    from app.threads.models import Thread
    from app.auth.models import User
    from sqlalchemy import select

    # Register user and get auth headers
    headers = await _auth_headers(client, db_session, "threads-type@test.dev")

    # Get the current test user
    user = (await db_session.execute(select(User).where(User.email == "threads-type@test.dev"))).scalars().first()

    # Create a news thread directly in DB
    news_thread = Thread(user_id=user.id, title="新闻助手", type="news")
    db_session.add(news_thread)
    await db_session.commit()

    # List threads via API
    r = await client.get("/api/threads/", headers=headers)
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()]

    # News thread should NOT appear in list
    assert str(news_thread.id) not in ids
