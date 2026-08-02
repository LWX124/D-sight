import uuid

import pytest
from sqlalchemy import func, select

from app.auth.models import User
from app.core.security import hash_password
from app.kb.ingest import ingest_document
from app.kb.models import Kb, KbChunk, KbDocument


async def _doc(db, filename="a.txt", title=None):
    u = User(email=f"ing-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db.add(u)
    await db.flush()
    kb = Kb(owner_id=u.id, name="k")
    db.add(kb)
    await db.flush()
    doc = KbDocument(kb_id=kb.id, title=title or filename or "unnamed",
                     filename=filename, source_type="upload" if filename else "news_item",
                     source_ref_id=None if filename else str(uuid.uuid4()), status="pending")
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


@pytest.mark.asyncio
async def test_ingest_text_stores_snapshot_and_chunks(db_session):
    """ingest_text 是三条来源共用的入库路径：切片 + 存正文快照 + 置 ready。"""
    from app.kb.ingest import ingest_text

    did = await _doc(db_session, filename=None, title="一篇公众号文章")
    await ingest_text(did, "贵州茅台2025年净利润大幅增长。" * 60)
    doc = await db_session.get(KbDocument, did)
    await db_session.refresh(doc)
    assert doc.status == "ready" and doc.chunk_count >= 1
    assert doc.text.startswith("贵州茅台")          # 快照落库，供详情页展示
    n = (await db_session.execute(
        select(func.count()).select_from(KbChunk).where(KbChunk.document_id == did)
    )).scalar_one()
    assert n == doc.chunk_count


@pytest.mark.asyncio
async def test_ingest_text_marks_failed_on_blank(db_session):
    """空正文切不出 chunk，进库只污染索引 → 标 failed。"""
    from app.kb.ingest import ingest_text

    did = await _doc(db_session, filename=None, title="空文章")
    await ingest_text(did, "   \n  ")
    doc = await db_session.get(KbDocument, did)
    await db_session.refresh(doc)
    assert doc.status == "failed" and "空" in (doc.error or "")


@pytest.mark.asyncio
async def test_ingest_text_writes_hash_and_model_on_chunks(db_session):
    from app.kb.embedding_cache import content_hash, current_embedding_model
    from app.kb.ingest import ingest_text

    did = await _doc(db_session, filename=None, title="带缓存键")
    await ingest_text(did, "一段够长的正文。" * 50)
    chunk = (await db_session.execute(
        select(KbChunk).where(KbChunk.document_id == did).order_by(KbChunk.ordinal).limit(1)
    )).scalar_one()
    assert chunk.content_hash == content_hash(chunk.content)
    assert chunk.embedding_model == current_embedding_model()
