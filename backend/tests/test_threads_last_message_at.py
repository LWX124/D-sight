import asyncio
from datetime import UTC, datetime
import uuid

from sqlalchemy import update

from app.core.db import get_sessionmaker
from app.threads.models import Thread
from tests.test_auth_api import _register


async def _auth_headers(client, db_session, email: str) -> dict:
    token = await _register(client, db_session, email)
    return {"Authorization": f"Bearer {token}"}


async def test_threads_sorted_by_last_message_at(client, db_session):
    """历史列表按 last_message_at 倒序，重命名不影响排序。"""
    headers = await _auth_headers(client, db_session, "sort@test.dev")

    tid_a = (await client.post("/api/threads/", json={}, headers=headers)).json()["id"]
    await asyncio.sleep(0.01)
    tid_b = (await client.post("/api/threads/", json={}, headers=headers)).json()["id"]
    await asyncio.sleep(0.01)
    tid_c = (await client.post("/api/threads/", json={}, headers=headers)).json()["id"]

    threads = (await client.get("/api/threads/", headers=headers)).json()
    assert [thread["id"] for thread in threads] == [tid_c, tid_b, tid_a]

    await client.patch(f"/api/threads/{tid_a}", json={"title": "重命名"}, headers=headers)
    threads = (await client.get("/api/threads/", headers=headers)).json()
    assert [thread["id"] for thread in threads] == [tid_c, tid_b, tid_a]

    async with get_sessionmaker().begin() as db:
        await db.execute(
            update(Thread)
            .where(Thread.id == uuid.UUID(tid_b))
            .values(last_message_at=datetime.now(UTC))
        )

    threads = (await client.get("/api/threads/", headers=headers)).json()
    assert [thread["id"] for thread in threads] == [tid_b, tid_c, tid_a]
