import logging
import uuid

from app.core.db import get_sessionmaker
from app.kb.chunking import chunk_text, parse_document
from app.kb.embedding_cache import content_hash, current_embedding_model, embed_with_cache
from app.kb.models import KbChunk, KbDocument

_log = logging.getLogger(__name__)


async def _mark_failed(document_id: uuid.UUID, message: str) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        doc = await s.get(KbDocument, document_id)
        if doc is not None:
            doc.status = "failed"
            doc.error = message[:500]
            await s.commit()


async def ingest_text(document_id: uuid.UUID, text: str) -> None:
    """切片 → 向量（复用缓存）→ 存 chunk → 置 ready。三条来源共用此路径。

    正文快照一并写入 KbDocument.text：详情页展示的必须是检索命中的这份文本，
    否则用户会看到「AI 引用的内容和我看到的不一样」。
    """
    sm = get_sessionmaker()
    try:
        async with sm() as s:
            doc = await s.get(KbDocument, document_id)
            if doc is None:
                return
            doc.status = "processing"
            await s.commit()

        pieces = chunk_text(text)
        if not pieces:
            await _mark_failed(document_id, "正文为空，未切出任何片段")
            return

        model = current_embedding_model()
        async with sm() as s:
            doc = await s.get(KbDocument, document_id)
            if doc is None:
                return
            vecs = await embed_with_cache(s, pieces)
            for ordinal, (content, vec) in enumerate(zip(pieces, vecs, strict=True)):
                s.add(KbChunk(
                    document_id=doc.id, kb_id=doc.kb_id, ordinal=ordinal,
                    content=content, embedding=vec,
                    content_hash=content_hash(content), embedding_model=model,
                ))
            doc.text = text
            doc.status = "ready"
            doc.error = None
            doc.chunk_count = len(pieces)
            await s.commit()
    except Exception as e:  # noqa: BLE001 — 后台任务：失败写库不抛
        _log.exception("ingest_text failed for %s", document_id)
        await _mark_failed(document_id, str(e))


async def ingest_document(document_id: uuid.UUID, filename: str, raw: bytes) -> None:
    """上传路径：解析文件 → 交给 ingest_text。行为与重构前一致。"""
    try:
        text = parse_document(filename, raw)
    except Exception as e:  # noqa: BLE001 — 解析失败（不支持的类型等）直接写库
        _log.exception("parse failed for %s", document_id)
        await _mark_failed(document_id, str(e))
        return
    await ingest_text(document_id, text)
