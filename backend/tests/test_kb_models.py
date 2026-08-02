import uuid

import pytest
from sqlalchemy import func, select

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
    doc = KbDocument(kb_id=kb.id, title="a.txt", filename="a.txt", status="ready", chunk_count=1)
    db_session.add(doc)
    await db_session.flush()
    chunk = KbChunk(document_id=doc.id, kb_id=kb.id, ordinal=0, content="正文", embedding=[0.1] * 1024,
                     content_hash="a" * 64, embedding_model="fake:BAAI/bge-m3")
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
    doc = KbDocument(kb_id=kb.id, title="v.txt", filename="v.txt", status="ready")
    db_session.add(doc)
    await db_session.flush()
    near = [1.0] + [0.0] * 1023
    far = [0.0] * 1023 + [1.0]
    db_session.add_all([
        KbChunk(document_id=doc.id, kb_id=kb.id, ordinal=0, content="近", embedding=near,
                 content_hash="a" * 64, embedding_model="fake:BAAI/bge-m3"),
        KbChunk(document_id=doc.id, kb_id=kb.id, ordinal=1, content="远", embedding=far,
                 content_hash="b" * 64, embedding_model="fake:BAAI/bge-m3"),
    ])
    await db_session.commit()
    from sqlalchemy import select
    rows = (await db_session.execute(
        select(KbChunk).where(KbChunk.kb_id == kb.id)
        .order_by(KbChunk.embedding.cosine_distance([1.0] + [0.0] * 1023)).limit(1)
    )).scalars().all()
    assert rows[0].content == "近"  # 余弦最近的是 near


@pytest.mark.asyncio
async def test_kb_source_and_document_source_fields(db_session):
    """新字段可写可读；(kb_id, source_type, source_ref_id) 唯一约束生效。"""
    import datetime as dt

    from sqlalchemy.exc import IntegrityError

    from app.kb.models import KbSource

    u = User(email=f"kbs-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add(u)
    await db_session.flush()
    kb = Kb(owner_id=u.id, name="社媒库")
    db_session.add(kb)
    await db_session.flush()

    src = KbSource(kb_id=kb.id, source_type="wechat_account",
                   source_ref_id=str(uuid.uuid4()), display_name="某公众号")
    db_session.add(src)
    await db_session.flush()
    assert src.status == "pending" and src.enabled is True

    ref = str(uuid.uuid4())
    doc = KbDocument(
        kb_id=kb.id, title="一篇文章", source_type="wechat_article", source_ref_id=ref,
        source_url="https://mp.weixin.qq.com/s/x", published_at=dt.datetime.now(dt.UTC),
        kb_source_id=src.id, text="正文快照", status="ready",
    )
    db_session.add(doc)
    await db_session.commit()
    got = await db_session.get(KbDocument, doc.id)
    assert got.filename is None and got.text == "正文快照"
    assert got.title == "一篇文章" and got.kb_source_id == src.id

    # 同库同源第二次插入 → 唯一约束拦下
    db_session.add(KbDocument(kb_id=kb.id, title="重复", source_type="wechat_article",
                              source_ref_id=ref, status="pending"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_upload_docs_with_null_source_ref_not_deduped(db_session):
    """上传文档 source_ref_id 为 NULL，Postgres 中 NULL 互不相等 → 同名文件仍可重复上传。"""
    u = User(email=f"kbu-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add(u)
    await db_session.flush()
    kb = Kb(owner_id=u.id, name="上传库")
    db_session.add(kb)
    await db_session.flush()
    for _ in range(2):
        db_session.add(KbDocument(kb_id=kb.id, title="a.txt", filename="a.txt",
                                  source_type="upload", status="pending"))
    await db_session.commit()  # 不应抛
    n = (await db_session.execute(
        select(func.count()).select_from(KbDocument).where(KbDocument.kb_id == kb.id)
    )).scalar_one()
    assert n == 2


@pytest.mark.asyncio
async def test_chunk_hash_and_model_columns(db_session):
    from app.kb.models import KbChunk

    u = User(email=f"kbc-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add(u)
    await db_session.flush()
    kb = Kb(owner_id=u.id, name="c")
    db_session.add(kb)
    await db_session.flush()
    doc = KbDocument(kb_id=kb.id, title="c.txt", filename="c.txt",
                     source_type="upload", status="ready")
    db_session.add(doc)
    await db_session.flush()
    ch = KbChunk(document_id=doc.id, kb_id=kb.id, ordinal=0, content="片段",
                 embedding=[0.1] * 1024, content_hash="a" * 64,
                 embedding_model="fake:BAAI/bge-m3")
    db_session.add(ch)
    await db_session.commit()
    got = await db_session.get(KbChunk, ch.id)
    assert got.content_hash == "a" * 64 and got.embedding_model == "fake:BAAI/bge-m3"
