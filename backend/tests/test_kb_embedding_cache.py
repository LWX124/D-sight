import uuid

import pytest

from app.auth.models import User
from app.core.security import hash_password
from app.kb.embedding_cache import (
    content_hash,
    current_embedding_model,
    embed_with_cache,
)
from app.kb.models import Kb, KbChunk, KbDocument


async def _kb(db):
    u = User(email=f"ec-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db.add(u)
    await db.flush()
    kb = Kb(owner_id=u.id, name="缓存库")
    db.add(kb)
    await db.flush()
    doc = KbDocument(kb_id=kb.id, title="d.txt", filename="d.txt",
                     source_type="upload", status="ready")
    db.add(doc)
    await db.commit()
    return kb, doc


def test_content_hash_is_stable_and_hex64():
    h = content_hash("贵州茅台")
    assert h == content_hash("贵州茅台") and len(h) == 64
    assert h != content_hash("五粮液")


def test_current_embedding_model_includes_backend():
    """缓存键必须带 backend：fake 后端算的假向量不能被 siliconflow 真索引复用。"""
    m = current_embedding_model()
    assert m.startswith("fake:")  # 测试环境 EMBEDDING_BACKEND=fake
    assert "/" in m               # 含模型名


@pytest.mark.asyncio
async def test_second_ingest_of_same_text_skips_provider(db_session, monkeypatch):
    kb, doc = await _kb(db_session)
    text = "同一段文本只应算一次向量。"

    # 先落一条 chunk 充当缓存
    vecs = await embed_with_cache(db_session, [text])
    db_session.add(KbChunk(
        document_id=doc.id, kb_id=kb.id, ordinal=0, content=text, embedding=vecs[0],
        content_hash=content_hash(text), embedding_model=current_embedding_model(),
    ))
    await db_session.commit()

    calls = []
    from app.kb import embedding_cache

    class CountingProvider:
        async def embed(self, texts):
            calls.append(list(texts))
            return [[0.5] * 1024 for _ in texts]

    monkeypatch.setattr(embedding_cache, "get_embedding_provider", lambda: CountingProvider())

    again = await embed_with_cache(db_session, [text])
    assert calls == []                      # 完全命中，未调 provider
    assert again[0] == pytest.approx(vecs[0], abs=1e-6)


@pytest.mark.asyncio
async def test_partial_hit_only_embeds_missing_and_keeps_order(db_session, monkeypatch):
    kb, doc = await _kb(db_session)
    cached, fresh = "已缓存的文本", f"未缓存-{uuid.uuid4().hex}"
    v = await embed_with_cache(db_session, [cached])
    db_session.add(KbChunk(
        document_id=doc.id, kb_id=kb.id, ordinal=0, content=cached, embedding=v[0],
        content_hash=content_hash(cached), embedding_model=current_embedding_model(),
    ))
    await db_session.commit()

    calls = []
    from app.kb import embedding_cache

    class CountingProvider:
        async def embed(self, texts):
            calls.append(list(texts))
            return [[0.25] * 1024 for _ in texts]

    monkeypatch.setattr(embedding_cache, "get_embedding_provider", lambda: CountingProvider())

    out = await embed_with_cache(db_session, [cached, fresh])
    assert calls == [[fresh]]               # 只算未命中的那条
    assert len(out) == 2
    assert out[0] == pytest.approx(v[0], abs=1e-6)   # 顺序与入参一致
    assert out[1] == [0.25] * 1024


@pytest.mark.asyncio
async def test_different_model_does_not_hit(db_session, monkeypatch):
    """换 embedding 模型后旧向量自然失效，不污染新索引。"""
    kb, doc = await _kb(db_session)
    text = f"换模型-{uuid.uuid4().hex}"
    v = await embed_with_cache(db_session, [text])
    db_session.add(KbChunk(
        document_id=doc.id, kb_id=kb.id, ordinal=0, content=text, embedding=v[0],
        content_hash=content_hash(text), embedding_model="other:some-model",
    ))
    await db_session.commit()

    calls = []
    from app.kb import embedding_cache

    class CountingProvider:
        async def embed(self, texts):
            calls.append(list(texts))
            return [[0.75] * 1024 for _ in texts]

    monkeypatch.setattr(embedding_cache, "get_embedding_provider", lambda: CountingProvider())

    out = await embed_with_cache(db_session, [text])
    assert calls == [[text]]                # 模型名不同 → 未命中
    assert out[0] == [0.75] * 1024


@pytest.mark.asyncio
async def test_duplicate_texts_within_one_batch_embed_once(db_session, monkeypatch):
    calls = []
    from app.kb import embedding_cache

    class CountingProvider:
        async def embed(self, texts):
            calls.append(list(texts))
            return [[0.1] * 1024 for _ in texts]

    monkeypatch.setattr(embedding_cache, "get_embedding_provider", lambda: CountingProvider())
    t = f"批内重复-{uuid.uuid4().hex}"
    out = await embed_with_cache(db_session, [t, t, t])
    assert calls == [[t]]                   # 批内去重
    assert len(out) == 3 and out[0] == out[1] == out[2]


@pytest.mark.asyncio
async def test_empty_input_returns_empty_without_provider(db_session, monkeypatch):
    calls = []
    from app.kb import embedding_cache

    class CountingProvider:
        async def embed(self, texts):
            calls.append(list(texts))
            return []

    monkeypatch.setattr(embedding_cache, "get_embedding_provider", lambda: CountingProvider())
    assert await embed_with_cache(db_session, []) == []
    assert calls == []
