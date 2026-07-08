import logging
import uuid

from app.core.db import get_sessionmaker
from app.kb.chunking import chunk_text, parse_document
from app.kb.models import KbChunk, KbDocument
from app.kb.providers import get_embedding_provider

_log = logging.getLogger(__name__)
_EMBED_BATCH = 32


async def ingest_document(document_id: uuid.UUID, filename: str, raw: bytes) -> None:
    sm = get_sessionmaker()
    try:
        async with sm() as s:
            doc = await s.get(KbDocument, document_id)
            if doc is None:
                return
            doc.status = "processing"
            await s.commit()

        text = parse_document(filename, raw)
        pieces = chunk_text(text)
        provider = get_embedding_provider()

        async with sm() as s:
            doc = await s.get(KbDocument, document_id)
            for base in range(0, len(pieces), _EMBED_BATCH):
                batch = pieces[base:base + _EMBED_BATCH]
                vecs = await provider.embed(batch)
                for offset, (content, vec) in enumerate(zip(batch, vecs, strict=True)):
                    s.add(KbChunk(
                        document_id=doc.id, kb_id=doc.kb_id, ordinal=base + offset,
                        content=content, embedding=vec,
                    ))
            doc.status = "ready"
            doc.chunk_count = len(pieces)
            await s.commit()
    except Exception as e:  # noqa: BLE001 — 后台任务：失败写库不抛
        _log.exception("ingest failed for %s", document_id)
        async with sm() as s:
            doc = await s.get(KbDocument, document_id)
            if doc is not None:
                doc.status = "failed"
                doc.error = str(e)[:500]
                await s.commit()
