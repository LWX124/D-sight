import uuid

import pytest

from app.auth.models import User
from app.core.security import hash_password
from app.kb.ingest import ingest_document
from app.kb.models import Kb, KbDocument, KbSubscription
from app.kb.retrieval import accessible_kb_ids, search_chunks


async def _kb_with_doc(db, owner, name, text):
    kb = Kb(owner_id=owner.id, name=name)
    db.add(kb)
    await db.flush()
    doc = KbDocument(kb_id=kb.id, filename=f"{name}.txt", status="pending")
    db.add(doc)
    await db.commit()
    await ingest_document(doc.id, doc.filename, text.encode("utf-8"))
    return kb


@pytest.mark.asyncio
async def test_search_returns_sourced_hits(db_session):
    u = User(email=f"r-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add(u)
    await db_session.flush()
    kb = await _kb_with_doc(db_session, u, "研报", "贵州茅台2025年报净利润增长强劲。")
    hits = await search_chunks(db_session, [kb.id], "茅台 净利润")
    assert hits and hits[0]["filename"] == "研报.txt" and "kb_id" in hits[0]


@pytest.mark.asyncio
async def test_accessible_filters_unowned_and_unshared(db_session):
    a = User(email=f"a-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    b = User(email=f"b-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add_all([a, b])
    await db_session.flush()
    kb_a = Kb(owner_id=a.id, name="A私有")
    db_session.add(kb_a)
    await db_session.flush()
    # b 请求 a 的私有库 → 不可见
    assert await accessible_kb_ids(db_session, b.id, [kb_a.id]) == []
    # a 自己可见
    assert await accessible_kb_ids(db_session, a.id, [kb_a.id]) == [kb_a.id]
    # b 订阅但 a 未共享 → 仍不可见
    db_session.add(KbSubscription(kb_id=kb_a.id, user_id=b.id))
    await db_session.commit()
    assert await accessible_kb_ids(db_session, b.id, [kb_a.id]) == []
