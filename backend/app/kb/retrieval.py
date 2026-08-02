import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kb.models import Kb, KbChunk, KbDocument, KbSubscription
from app.kb.providers import get_embedding_provider, get_reranker


async def accessible_kb_ids(db: AsyncSession, user_id: uuid.UUID, requested: list[uuid.UUID]) -> list[uuid.UUID]:
    if not requested:
        return []
    owned = {k for (k,) in (await db.execute(
        select(Kb.id).where(Kb.owner_id == user_id, Kb.id.in_(requested))
    )).all()}
    subbed = {k for (k,) in (await db.execute(
        select(Kb.id).join(KbSubscription, KbSubscription.kb_id == Kb.id)
        .where(KbSubscription.user_id == user_id, Kb.is_shared.is_(True), Kb.id.in_(requested))
    )).all()}
    return list(owned | subbed)


async def search_chunks(db, kb_ids, query, top_k=20, top_n=5) -> list[dict]:
    if not kb_ids:
        return []
    qvec = (await get_embedding_provider().embed([query]))[0]
    rows = (await db.execute(
        select(KbChunk, KbDocument.title)
        .join(KbDocument, KbDocument.id == KbChunk.document_id)
        .where(KbChunk.kb_id.in_(kb_ids))
        .order_by(KbChunk.embedding.cosine_distance(qvec)).limit(top_k)
    )).all()
    if not rows:
        return []
    docs = [c.content for c, _ in rows]
    ranked = await get_reranker().rerank(query, docs, top_n)
    out = []
    for idx, score in ranked:
        chunk, title = rows[idx]
        # 键名保持 filename：agent/tools/kb.py 与既有测试都读这个键，
        # 上传文档的 title 本就等于文件名，语义不变。
        out.append({"content": chunk.content, "kb_id": str(chunk.kb_id),
                    "document_id": str(chunk.document_id), "filename": title, "score": score})
    return out
