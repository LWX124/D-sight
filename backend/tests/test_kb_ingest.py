import uuid

import pytest
from sqlalchemy import func, select

from app.auth.models import User
from app.core.security import hash_password
from app.kb.ingest import ingest_document
from app.kb.models import Kb, KbChunk, KbDocument


async def _doc(db, filename="a.txt"):
    u = User(email=f"ing-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db.add(u)
    await db.flush()
    kb = Kb(owner_id=u.id, name="k")
    db.add(kb)
    await db.flush()
    doc = KbDocument(kb_id=kb.id, filename=filename, status="pending")
    db.add(doc)
    await db.commit()
    return doc.id


@pytest.mark.asyncio
async def test_ingest_ready_with_chunks(db_session):
    did = await _doc(db_session)
    await ingest_document(did, "a.txt", ("一" * 1000).encode("utf-8"))
    doc = await db_session.get(KbDocument, did)
    await db_session.refresh(doc)
    assert doc.status == "ready" and doc.chunk_count >= 1
    n = (await db_session.execute(
        select(func.count()).select_from(KbChunk).where(KbChunk.document_id == did)
    )).scalar_one()
    assert n == doc.chunk_count


@pytest.mark.asyncio
async def test_ingest_bad_type_marks_failed(db_session):
    did = await _doc(db_session, filename="a.exe")
    await ingest_document(did, "a.exe", b"x")
    doc = await db_session.get(KbDocument, did)
    await db_session.refresh(doc)
    assert doc.status == "failed" and "txt/md/pdf" in (doc.error or "")
