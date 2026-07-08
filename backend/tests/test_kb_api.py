import asyncio
import io

import pytest

from tests.conftest import _auth


@pytest.mark.asyncio
async def test_kb_crud_and_upload_flow(client, db_session, registered_user):
    h = _auth(registered_user)
    r = await client.post("/api/kb", json={"name": "研报库"}, headers=h)
    assert r.status_code == 200
    kb_id = r.json()["id"]

    files = {"file": ("a.txt", io.BytesIO("一二三四五".encode("utf-8")), "text/plain")}
    up = await client.post(f"/api/kb/{kb_id}/documents", files=files, headers=h)
    assert up.status_code == 200 and up.json()["status"] == "pending"

    # BackgroundTasks 在响应后同事件循环执行；轮询文档状态直到非 pending
    for _ in range(50):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if docs and docs[0]["status"] in ("ready", "failed"):
            break
        await asyncio.sleep(0.1)
    assert docs[0]["status"] == "ready" and docs[0]["chunk_count"] >= 1


@pytest.mark.asyncio
async def test_upload_rejects_bad_type_and_foreign_kb(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "x"}, headers=h)).json()["id"]
    bad = {"file": ("a.exe", io.BytesIO(b"x"), "application/octet-stream")}
    assert (await client.post(f"/api/kb/{kb_id}/documents", files=bad, headers=h)).status_code == 400
    # 他人 KB
    assert (await client.get("/api/kb/00000000-0000-0000-0000-000000000000/documents", headers=h)).status_code == 404
