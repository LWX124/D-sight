import hashlib
import math
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.kb.models import EMBEDDING_DIM

SILICONFLOW_BASE = "https://api.siliconflow.cn/v1"


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class Reranker(Protocol):
    async def rerank(self, query: str, docs: list[str], top_n: int) -> list[tuple[int, float]]: ...


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class FakeEmbedding:
    """确定性离线 embedding：文本 → sha256 展开成 1024 维单位向量。相同文本同向量。"""

    def __init__(self, dim: int = 1024):
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            seed = hashlib.sha256(t.encode("utf-8")).digest()
            raw = [seed[i % len(seed)] - 128 for i in range(self.dim)]
            out.append(_unit([float(x) for x in raw]))
        return out


class FakeReranker:
    async def rerank(self, query: str, docs: list[str], top_n: int) -> list[tuple[int, float]]:
        qset = set(query)
        scored = [(i, len(qset & set(d)) / (len(qset) or 1)) for i, d in enumerate(docs)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]


class SiliconFlowEmbedding:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        s = get_settings()
        if not s.siliconflow_api_key:
            raise RuntimeError("SILICONFLOW_API_KEY 未配置")
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"{SILICONFLOW_BASE}/embeddings",
                headers={"Authorization": f"Bearer {s.siliconflow_api_key}"},
                json={"model": s.embedding_model, "input": texts},
            )
            r.raise_for_status()
            data = r.json()["data"]
            return [d["embedding"] for d in sorted(data, key=lambda x: x["index"])]


class SiliconFlowReranker:
    async def rerank(self, query: str, docs: list[str], top_n: int) -> list[tuple[int, float]]:
        s = get_settings()
        if not s.siliconflow_api_key:
            raise RuntimeError("SILICONFLOW_API_KEY 未配置")
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"{SILICONFLOW_BASE}/rerank",
                headers={"Authorization": f"Bearer {s.siliconflow_api_key}"},
                json={"model": s.rerank_model, "query": query, "documents": docs, "top_n": top_n},
            )
            r.raise_for_status()
            return [(x["index"], x["relevance_score"]) for x in r.json()["results"]]


def get_embedding_provider() -> EmbeddingProvider:
    b = get_settings().embedding_backend
    if b == "fake":
        return FakeEmbedding(EMBEDDING_DIM)
    if b == "siliconflow":
        return SiliconFlowEmbedding()
    raise RuntimeError(f"未知 EMBEDDING_BACKEND: {b!r}")


def get_reranker() -> Reranker:
    b = get_settings().embedding_backend
    if b == "fake":
        return FakeReranker()
    if b == "siliconflow":
        return SiliconFlowReranker()
    raise RuntimeError(f"未知 EMBEDDING_BACKEND: {b!r}")
