"""向量复用：同一段文本在任何知识库里只调一次 embedding API。

不建独立缓存表——直接查 kb_chunks。这样不需要任何清理策略：最后一个引用该文本的
chunk 被删除时，「缓存」自动随之消失。存储上文本副本各存一份（几 KB），省下的是
按量计费的 API 调用。
"""
import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.kb.models import KbChunk
from app.kb.providers import get_embedding_provider

_EMBED_BATCH = 32


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def current_embedding_model() -> str:
    """缓存键里的模型标识。

    带上 backend 前缀是必须的：本地以 EMBEDDING_BACKEND=fake 跑出的确定性假向量，
    与 siliconflow 真向量的 embedding_model 配置值相同，光靠模型名区分不开，
    会让假向量污染真索引。
    """
    s = get_settings()
    return f"{s.embedding_backend}:{s.embedding_model}"


async def embed_with_cache(db: AsyncSession, texts: list[str]) -> list[list[float]]:
    """返回与 texts 等长同序的向量；已有相同文本的向量则复用，只对缺的调 provider。"""
    if not texts:
        return []
    model = current_embedding_model()
    # 批内先去重：同一批里重复的文本只需算一次
    hashes = [content_hash(t) for t in texts]
    uniq: dict[str, str] = {}          # hash → text
    for h, t in zip(hashes, texts, strict=True):
        uniq.setdefault(h, t)

    found: dict[str, list[float]] = {}
    rows = (await db.execute(
        select(KbChunk.content_hash, KbChunk.embedding)
        .where(KbChunk.content_hash.in_(list(uniq)), KbChunk.embedding_model == model)
    )).all()
    for h, vec in rows:
        found.setdefault(h, list(vec))

    missing = [(h, t) for h, t in uniq.items() if h not in found]
    if missing:
        provider = get_embedding_provider()
        for base in range(0, len(missing), _EMBED_BATCH):
            batch = missing[base:base + _EMBED_BATCH]
            vecs = await provider.embed([t for _, t in batch])
            for (h, _), vec in zip(batch, vecs, strict=True):
                found[h] = list(vec)

    return [found[h] for h in hashes]
