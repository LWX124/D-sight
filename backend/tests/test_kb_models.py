import uuid

import pytest

from app.auth.models import User
from app.core.security import hash_password
from app.kb.models import Kb, KbChunk, KbDocument


@pytest.mark.asyncio
async def test_kb_document_chunk_roundtrip(db_session):
    u = User(email=f"kb-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add(u)
    await db_session.flush()
    kb = Kb(owner_id=u.id, name="研报库")
    db_session.add(kb)
    await db_session.flush()
    doc = KbDocument(kb_id=kb.id, filename="a.txt", status="ready", chunk_count=1)
    db_session.add(doc)
    await db_session.flush()
    chunk = KbChunk(document_id=doc.id, kb_id=kb.id, ordinal=0, content="正文", embedding=[0.1] * 1024)
    db_session.add(chunk)
    await db_session.commit()
    got = await db_session.get(KbChunk, chunk.id)
    assert got.ordinal == 0 and len(got.embedding) == 1024


@pytest.mark.asyncio
async def test_vector_cosine_search(db_session):
    u = User(email=f"kbv-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add(u)
    await db_session.flush()
    kb = Kb(owner_id=u.id, name="v")
    db_session.add(kb)
    await db_session.flush()
    doc = KbDocument(kb_id=kb.id, filename="v.txt", status="ready")
    db_session.add(doc)
    await db_session.flush()
    near = [1.0] + [0.0] * 1023
    far = [0.0] * 1023 + [1.0]
    db_session.add_all([
        KbChunk(document_id=doc.id, kb_id=kb.id, ordinal=0, content="近", embedding=near),
        KbChunk(document_id=doc.id, kb_id=kb.id, ordinal=1, content="远", embedding=far),
    ])
    await db_session.commit()
    from sqlalchemy import select
    rows = (await db_session.execute(
        select(KbChunk).where(KbChunk.kb_id == kb.id)
        .order_by(KbChunk.embedding.cosine_distance([1.0] + [0.0] * 1023)).limit(1)
    )).scalars().all()
    assert rows[0].content == "近"  # 余弦最近的是 near
