# 骨架计划 5：知识库 RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户上传文档 → 异步切片向量化入库 → 聊天中挂载知识库 → agent 用 `kb_search` 工具检索（向量召回 + 重排 + 带出处），并支持只读全库共享/订阅。

**Architecture:** 新增 `kb` 模块（models/service/router/ingest/retrieval）。embedding/rerank 走 provider 抽象：默认 SiliconFlow 托管 `BGE-M3` / `BGE-reranker-v2-m3`（满足 spec 模型选型且轻依赖），另有确定性 fake provider 供离线测试。上传触发 FastAPI BackgroundTask 跑摄取管道（pending→processing→ready/failed），切片向量存 pgvector（HNSW 余弦索引）。检索 = 向量 top-20 → reranker top-5 → 带 kb/文档出处返回。`kb_search` 作为 per-request 绑定的 agent 工具（工厂注入已挂载 kb_id + 用户），聊天是唯一入口，无独立问答页。

**Tech Stack:** FastAPI（UploadFile/BackgroundTasks）、SQLAlchemy 2 async、pgvector（`Vector` 列 + HNSW）、httpx（SiliconFlow API）、pypdf、Alembic。

## Global Constraints

- Python 3.12 / uv / pytest + testcontainers（镜像已是 `pgvector/pgvector:pg16`，pgvector 扩展可用；ryuk flaky → `TESTCONTAINERS_RYUK_DISABLED=true`）。
- embedding 维度 **1024**（BGE-M3）；向量列 `Vector(1024)`，HNSW `vector_cosine_ops`。
- provider 抽象 fail-loud：`EMBEDDING_BACKEND ∈ {fake, siliconflow}`，未知值 → RuntimeError（仿 `email_backend`）。测试默认 `fake`，不联网不花钱；`siliconflow` 需 `SILICONFLOW_API_KEY`。
- 一切检索**只读**，不改积分（KB 检索不单独计费——skill 定价已覆盖研究类；如需 KB 计费归后续）。
- 沙箱/安全：上传文件大小上限（默认 10MB）、仅 `txt/md/pdf`；文件内容只解析不执行。
- KB 归属：`kb.owner_id`；检索范围 = 自有 KB ∪ 已订阅且 owner 仍开启共享的 KB。
- alembic autogenerate 已有 `include_object` 过滤 checkpoint；`Vector` 列与 HNSW 索引 autogenerate 可能不完整，**迁移人工补 `CREATE EXTENSION`/HNSW 并 Read 确认**。
- 前端 API 走 `apiFetch`（401 刷新）；页面元素带 `data-testid`。
- 分支 `skeleton-5` 从 `main` 起；本地 commit 已授权，不 push（等用户 `c&p`）。
- deepagents 工具可为 async（langgraph ToolNode await 异步工具）；`kb_search` 用 async `@tool`，内部开自己的 DB session。

---

### Task 0: 分支与骨架

**Files:** Create `backend/app/kb/__init__.py`

- [ ] **Step 1**
```bash
cd /Users/weixi1/Documents/mine/D-sight && git checkout main && git checkout -b skeleton-5
mkdir -p backend/app/kb && touch backend/app/kb/__init__.py
git add backend/app/kb/__init__.py
git commit -m "chore(kb): scaffold kb package"
```

---

### Task 1: pgvector 启用 + 数据模型 + 迁移

**Files:**
- Create: `backend/app/kb/models.py`
- Modify: `backend/alembic/env.py`（导入模型）
- Modify: `backend/pyproject.toml`（加 `pgvector`）
- Create: migration（autogenerate + 人工补 extension/HNSW）
- Test: `backend/tests/test_kb_models.py`

**Interfaces:**
- Produces:
  - `Kb(id: UUID, owner_id: UUID FK CASCADE, name: str, is_shared: bool=False, share_slug: str|None unique, created_at, updated_at)`
  - `KbDocument(id: UUID, kb_id: UUID FK CASCADE, filename: str, status: str[pending/processing/ready/failed], error: str|None, chunk_count: int=0, created_at, updated_at)`
  - `KbChunk(id: UUID, document_id: UUID FK CASCADE, kb_id: UUID FK CASCADE index, ordinal: int, content: str, embedding: Vector(1024), created_at)`
  - `KbSubscription(id: UUID, kb_id: UUID FK CASCADE, user_id: UUID FK CASCADE, created_at)`，`UniqueConstraint(kb_id, user_id)`

- [ ] **Step 1: 依赖**
```bash
cd backend && uv add pgvector
```

- [ ] **Step 2: 模型**

`backend/app/kb/models.py`:
```python
import datetime as dt
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

EMBEDDING_DIM = 1024


class Kb(Base):
    __tablename__ = "kb"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    share_slug: Mapped[str | None] = mapped_column(String(32), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KbDocument(Base):
    __tablename__ = "kb_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KbChunk(Base):
    __tablename__ = "kb_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_documents.id", ondelete="CASCADE"), index=True)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KbSubscription(Base):
    __tablename__ = "kb_subscriptions"
    __table_args__ = (UniqueConstraint("kb_id", "user_id", name="uq_kb_subscription"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 3: alembic 发现 + 生成**

`alembic/env.py` 加 `from app.kb import models as kb_models  # noqa: F401`。
```bash
cd backend && uv run alembic revision --autogenerate -m "kb"
```

- [ ] **Step 4: 人工补 extension + HNSW**

autogenerate **不会**生成 `CREATE EXTENSION`，且 `Vector` 列/HNSW 索引可能缺失或报错。编辑生成的迁移：
- `upgrade()` 顶部加 `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`（必须在 create_table 之前）。
- 确认 `kb_chunks.embedding` 列类型为 `Vector(1024)`（若 autogenerate 渲染为 `sa.NullType` 之类，手写 `import pgvector.sqlalchemy` 并用 `pgvector.sqlalchemy.Vector(1024)`）。
- 在 create_table 之后加 HNSW 索引：
  ```python
  op.execute(
      "CREATE INDEX ix_kb_chunks_embedding ON kb_chunks "
      "USING hnsw (embedding vector_cosine_ops)"
  )
  ```
- `downgrade()` 对称 drop（drop index → tables；extension 可不 drop）。
Read 整个迁移确认三点：extension 在前、Vector 类型正确、HNSW 索引在。

- [ ] **Step 5: 往返测试**

`backend/tests/test_kb_models.py`:
```python
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
```

- [ ] **Step 6: 跑测试 + Commit**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_kb_models.py -q`
Expected: 2 passed（testcontainer 的 pgvector 镜像 + 迁移里的 CREATE EXTENSION 使 vector 类型与 HNSW 可用）

```bash
git add backend/app/kb/models.py backend/alembic/ backend/pyproject.toml backend/uv.lock backend/tests/test_kb_models.py
git commit -m "feat(kb): pgvector models, extension and HNSW migration"
```

---

### Task 2: embedding / rerank provider 抽象

**Files:**
- Create: `backend/app/kb/providers.py`
- Modify: `backend/app/core/config.py`（embedding 设置）
- Test: `backend/tests/test_kb_providers.py`

**Interfaces:**
- Produces:
  - `class EmbeddingProvider(Protocol): async def embed(self, texts: list[str]) -> list[list[float]]`
  - `class Reranker(Protocol): async def rerank(self, query: str, docs: list[str], top_n: int) -> list[tuple[int, float]]`（返回 (原始索引, 分数) 降序）
  - `FakeEmbedding`（确定性：每段文本 hash → 1024 维单位向量，**离线**）；`FakeReranker`（按 query 与 doc 的字符重叠率打分）
  - `SiliconFlowEmbedding` / `SiliconFlowReranker`（httpx 调 `https://api.siliconflow.cn/v1/embeddings` model `BAAI/bge-m3`、`/v1/rerank` model `BAAI/bge-reranker-v2-m3`）
  - `get_embedding_provider() -> EmbeddingProvider`、`get_reranker() -> Reranker`（依 `embedding_backend` fail-loud）

- [ ] **Step 1: 配置**

`Settings` 加：
```python
    embedding_backend: str = "fake"        # fake / siliconflow
    siliconflow_api_key: str = ""
    embedding_model: str = "BAAI/bge-m3"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    embedding_dim: int = 1024
```

- [ ] **Step 2: providers**

`backend/app/kb/providers.py`:
```python
import hashlib
import math
from typing import Protocol

import httpx

from app.core.config import get_settings

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
        return FakeEmbedding(get_settings().embedding_dim)
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
```

- [ ] **Step 3: 测试**

`backend/tests/test_kb_providers.py`:
```python
import pytest

from app.kb import providers


@pytest.mark.asyncio
async def test_fake_embedding_deterministic_and_unit():
    p = providers.FakeEmbedding(1024)
    a = await p.embed(["贵州茅台", "贵州茅台"])
    assert a[0] == a[1] and len(a[0]) == 1024
    import math
    assert abs(math.sqrt(sum(x * x for x in a[0])) - 1.0) < 1e-6
    b = await p.embed(["不同文本"])
    assert b[0] != a[0]


@pytest.mark.asyncio
async def test_fake_reranker_orders_by_overlap():
    r = providers.FakeReranker()
    out = await r.rerank("茅台财报", ["茅台财报很好", "无关内容", "茅台"], top_n=2)
    assert len(out) == 2 and out[0][0] == 0  # 重叠最多的排第一


def test_get_provider_failloud(monkeypatch):
    monkeypatch.setattr("app.kb.providers.get_settings",
                        lambda: type("S", (), {"embedding_backend": "nope", "embedding_dim": 1024})())
    with pytest.raises(RuntimeError):
        providers.get_embedding_provider()
    with pytest.raises(RuntimeError):
        providers.get_reranker()
```

- [ ] **Step 4: 跑测试 + Commit**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_kb_providers.py -q`
Expected: 3 passed

```bash
git add backend/app/kb/providers.py backend/app/core/config.py backend/tests/test_kb_providers.py
git commit -m "feat(kb): embedding/rerank provider abstraction with fake and siliconflow"
```

---

### Task 3: 文件解析 + 切片

**Files:**
- Create: `backend/app/kb/chunking.py`
- Modify: `backend/pyproject.toml`（加 `pypdf`）
- Test: `backend/tests/test_kb_chunking.py`

**Interfaces:**
- Produces:
  - `parse_document(filename: str, raw: bytes) -> str`（按扩展名：txt/md 用 strict-utf-8 试解码回退 gb18030；pdf 用 pypdf 抽文本；其它扩展名 → ValueError）
  - `chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[str]`（按字符窗口切，重叠；跳过纯空白块）

- [ ] **Step 1: 依赖**
```bash
cd backend && uv add pypdf
```

- [ ] **Step 2: 实现**

`backend/app/kb/chunking.py`:
```python
import io


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gb18030", errors="replace")


def parse_document(filename: str, raw: bytes) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("txt", "md"):
        return _decode(raw)
    if ext == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    raise ValueError(f"不支持的文件类型：.{ext}（仅 txt/md/pdf）")


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks, start, n = [], 0, len(text)
    step = max(1, size - overlap)
    while start < n:
        piece = text[start:start + size].strip()
        if piece:
            chunks.append(piece)
        start += step
    return chunks
```

- [ ] **Step 3: 测试**

`backend/tests/test_kb_chunking.py`:
```python
import pytest

from app.kb.chunking import chunk_text, parse_document


def test_parse_txt_utf8_and_gbk():
    assert parse_document("a.txt", "贵州茅台".encode("utf-8")) == "贵州茅台"
    assert parse_document("a.md", "贵州茅台".encode("gb18030")) == "贵州茅台"


def test_parse_rejects_unknown_ext():
    with pytest.raises(ValueError):
        parse_document("a.exe", b"x")


def test_chunk_overlap_and_skip_blank():
    text = "一" * 1000
    chunks = chunk_text(text, size=400, overlap=100)
    assert len(chunks) == 3  # 0-400, 300-700, 600-1000
    assert all(len(c) <= 400 for c in chunks)
    assert chunk_text("   \n  ") == []
```

- [ ] **Step 4: 跑测试 + Commit**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_kb_chunking.py -q`
Expected: 3 passed

```bash
git add backend/app/kb/chunking.py backend/pyproject.toml backend/uv.lock backend/tests/test_kb_chunking.py
git commit -m "feat(kb): document parsing (txt/md/pdf) and character chunking"
```

---

### Task 4: 摄取管道（异步入库 + 状态机）

**Files:**
- Create: `backend/app/kb/ingest.py`
- Test: `backend/tests/test_kb_ingest.py`

**Interfaces:**
- Consumes: `parse_document`/`chunk_text`（T3）、`get_embedding_provider`（T2）、`KbDocument`/`KbChunk`（T1）。
- Produces:
  - `async def ingest_document(document_id: UUID, filename: str, raw: bytes) -> None`（开自己的 session：置 processing → parse → chunk → 批量 embed → 写 KbChunk → 置 ready + chunk_count；任何异常 → 置 failed + error 文本，不抛出（后台任务吞异常并记库））

- [ ] **Step 1: 实现**

`backend/app/kb/ingest.py`:
```python
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
```

- [ ] **Step 2: 测试**

`backend/tests/test_kb_ingest.py`:
```python
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
```
（`db_session` 与 ingest 内部各自开 session；`refresh` 确保读到后台事务写入。若 refresh 读不到，改用新 `select` 查库。）

- [ ] **Step 3: 跑测试 + Commit**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_kb_ingest.py -q`
Expected: 2 passed（EMBEDDING_BACKEND 默认 fake，离线）

```bash
git add backend/app/kb/ingest.py backend/tests/test_kb_ingest.py
git commit -m "feat(kb): async ingestion pipeline with status machine"
```

---

### Task 5: KB / 文档 API

**Files:**
- Create: `backend/app/kb/router.py`、`backend/app/kb/schemas.py`
- Modify: `backend/app/main.py`（挂载）、`backend/pyproject.toml`（加 `python-multipart`）
- Modify: `backend/app/core/config.py`（`kb_max_upload_mb: int = 10`）
- Test: `backend/tests/test_kb_api.py`

**Interfaces:**
- Consumes: `get_current_user`、`ingest_document`（后台任务）、`Kb`/`KbDocument`。
- Produces:
  - `POST /api/kb` `{name}` → 建 KB（owner=当前用户）→ `{id,name}`
  - `GET /api/kb` → 自有 KB 列表 `[{id,name,is_shared,doc_count}]`
  - `POST /api/kb/{id}/documents`（multipart file）→ 校验大小/类型 → 建 pending 文档 → `BackgroundTasks.add_task(ingest_document, ...)` → `{document_id,status:"pending"}`（非本人 KB 404）
  - `GET /api/kb/{id}/documents` → `[{id,filename,status,chunk_count,error}]`（非本人 404）
  - `DELETE /api/kb/{id}` → 删 KB（级联文档/切片）（非本人 404）

- [ ] **Step 1: 依赖**
```bash
cd backend && uv add python-multipart
```

- [ ] **Step 2: schemas + router**

`backend/app/kb/schemas.py`:
```python
from pydantic import BaseModel


class KbCreate(BaseModel):
    name: str


class KbOut(BaseModel):
    id: str
    name: str
    is_shared: bool
    doc_count: int
```

`backend/app/kb/router.py`:
```python
import uuid

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.config import get_settings
from app.core.db import get_db
from app.kb.ingest import ingest_document
from app.kb.models import Kb, KbDocument
from app.kb.schemas import KbCreate, KbOut

router = APIRouter(prefix="/api/kb", tags=["kb"])
_ALLOWED = {"txt", "md", "pdf"}


async def _owned_kb(db: AsyncSession, user: User, kb_id: str) -> Kb:
    try:
        kid = uuid.UUID(kb_id)
    except ValueError:
        raise HTTPException(404, "知识库不存在")
    kb = await db.get(Kb, kid)
    if kb is None or kb.owner_id != user.id:
        raise HTTPException(404, "知识库不存在")
    return kb


@router.post("", response_model=KbOut)
async def create_kb(body: KbCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = Kb(owner_id=user.id, name=body.name)
    db.add(kb)
    await db.commit()
    return {"id": str(kb.id), "name": kb.name, "is_shared": kb.is_shared, "doc_count": 0}


@router.get("", response_model=list[KbOut])
async def list_kb(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kbs = (await db.execute(select(Kb).where(Kb.owner_id == user.id).order_by(Kb.created_at))).scalars().all()
    out = []
    for kb in kbs:
        n = (await db.execute(
            select(func.count()).select_from(KbDocument).where(KbDocument.kb_id == kb.id)
        )).scalar_one()
        out.append({"id": str(kb.id), "name": kb.name, "is_shared": kb.is_shared, "doc_count": n})
    return out


@router.post("/{kb_id}/documents")
async def upload_document(
    kb_id: str, background: BackgroundTasks, file: UploadFile = File(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    kb = await _owned_kb(db, user, kb_id)
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in _ALLOWED:
        raise HTTPException(400, "仅支持 txt/md/pdf")
    raw = await file.read()
    if len(raw) > get_settings().kb_max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "文件过大")
    doc = KbDocument(kb_id=kb.id, filename=file.filename or "unnamed", status="pending")
    db.add(doc)
    await db.commit()
    background.add_task(ingest_document, doc.id, doc.filename, raw)
    return {"document_id": str(doc.id), "status": "pending"}


@router.get("/{kb_id}/documents")
async def list_documents(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await _owned_kb(db, user, kb_id)
    docs = (await db.execute(
        select(KbDocument).where(KbDocument.kb_id == kb.id).order_by(KbDocument.created_at)
    )).scalars().all()
    return [{"id": str(d.id), "filename": d.filename, "status": d.status,
             "chunk_count": d.chunk_count, "error": d.error} for d in docs]


@router.delete("/{kb_id}")
async def delete_kb(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await _owned_kb(db, user, kb_id)
    await db.delete(kb)
    await db.commit()
    return {"deleted": True}
```
`main.py`：挂载 `kb_router`。`Settings` 加 `kb_max_upload_mb: int = 10`。

- [ ] **Step 3: 测试**

`backend/tests/test_kb_api.py`:
```python
import io

import pytest
from sqlalchemy import select

from app.kb.models import KbDocument


@pytest.mark.asyncio
async def test_kb_crud_and_upload_flow(client, db_session, registered_user):
    h = _auth(registered_user)
    r = await client.post("/api/kb", json={"name": "研报库"}, headers=h)
    assert r.status_code == 200
    kb_id = r.json()["id"]

    files = {"file": ("a.txt", io.BytesIO("一二三四五".encode("utf-8")), "text/plain")}
    up = await client.post(f"/api/kb/{kb_id}/documents", files=files, headers=h)
    assert up.status_code == 200 and up.json()["status"] == "pending"

    # BackgroundTasks 在响应后同事件循环执行；轮询文档状态直到非 pending
    import asyncio
    for _ in range(50):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if docs and docs[0]["status"] in ("ready", "failed"):
            break
        await asyncio.sleep(0.1)
    assert docs[0]["status"] == "ready" and docs[0]["chunk_count"] >= 1


@pytest.mark.asyncio
async def test_upload_rejects_bad_type_and_foreign_kb(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "x"}, headers=h)).json()["id"]
    bad = {"file": ("a.exe", io.BytesIO(b"x"), "application/octet-stream")}
    assert (await client.post(f"/api/kb/{kb_id}/documents", files=bad, headers=h)).status_code == 400
    # 他人 KB
    assert (await client.get("/api/kb/00000000-0000-0000-0000-000000000000/documents", headers=h)).status_code == 404
```
（`registered_user`/`_auth` 用 conftest 夹具。BackgroundTasks 在 ASGITransport 下是否执行：FastAPI 在响应返回后于同一事件循环 await 后台任务——轮询即可观察到 ready。若测试环境不执行后台任务，改为在测试里直接 `await ingest_document(...)` 并注明。）

- [ ] **Step 4: 跑测试 + Commit**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_kb_api.py -q`
Expected: 2 passed

```bash
git add backend/app/kb/router.py backend/app/kb/schemas.py backend/app/main.py backend/app/core/config.py backend/pyproject.toml backend/uv.lock backend/tests/test_kb_api.py
git commit -m "feat(kb): kb crud and document upload with background ingestion"
```

---

### Task 6: 检索服务 + kb_search 工具 + 聊天接线

**Files:**
- Create: `backend/app/kb/retrieval.py`、`backend/app/agent/tools/kb.py`
- Modify: `backend/app/agent/build.py`（`build_agent` 加 `kb_ids` 参数并注入工具）
- Modify: `backend/app/chat/router.py`（读 `mounted_kb_ids` 传入）、`backend/app/chat/schemas.py`（加字段）
- Test: `backend/tests/test_kb_retrieval.py`

**Interfaces:**
- Consumes: `get_embedding_provider`/`get_reranker`、`KbChunk`、`Kb`/`KbSubscription`。
- Produces:
  - `async def accessible_kb_ids(db, user_id, requested: list[UUID]) -> list[UUID]`（requested ∩（自有 ∪ 已订阅且 owner is_shared 仍开））
  - `async def search_chunks(db, kb_ids: list[UUID], query: str, top_k: int = 20, top_n: int = 5) -> list[dict]`（embed query → pgvector 余弦 top_k → reranker top_n → 返回 `[{content, kb_id, document_id, filename, score}]`）
  - `make_kb_search(session_factory, user_id, kb_ids)` → async `@tool kb_search(query: str) -> str`（无挂载 KB 时返回提示；有则检索并带出处格式化）
  - `build_agent(thread_id, checkpointer=None, skill_rows=None, kb_ids=None)`：`kb_ids` 非空 → 工具列表追加 `make_kb_search(get_sessionmaker(), user_id, kb_ids)`。**注意** `build_agent` 需要 user_id——新增参数 `user_id=None`；chat 端点传入。
  - `ChatRequest` 加 `mounted_kb_ids: list[str] | None = Field(default=None, alias="mountedKbIds")`

- [ ] **Step 1: 检索服务**

`backend/app/kb/retrieval.py`:
```python
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
        select(KbChunk, KbDocument.filename)
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
        chunk, filename = rows[idx]
        out.append({"content": chunk.content, "kb_id": str(chunk.kb_id),
                    "document_id": str(chunk.document_id), "filename": filename, "score": score})
    return out
```

- [ ] **Step 2: kb_search 工具**

`backend/app/agent/tools/kb.py`:
```python
import uuid

from langchain_core.tools import tool

from app.agent.tools.safe import tool_guard
from app.kb.retrieval import accessible_kb_ids, search_chunks


def make_kb_search(session_factory, user_id: uuid.UUID, kb_ids: list[uuid.UUID]):
    @tool
    @tool_guard
    async def kb_search(query: str) -> str:
        """在用户挂载的知识库中检索相关片段，返回带出处的内容。适合查已上传的研报/资料。"""
        async with session_factory() as db:
            allowed = await accessible_kb_ids(db, user_id, kb_ids)
            if not allowed:
                return "（未挂载可用知识库）"
            hits = await search_chunks(db, allowed, query)
        if not hits:
            return "（知识库中未检索到相关内容）"
        return "\n\n".join(
            f"[出处：{h['filename']}]\n{h['content']}" for h in hits
        )

    return kb_search
```
（`tool_guard` 是否支持 async：Read `app/agent/tools/safe.py` 确认；若 `tool_guard` 仅包同步函数，则 async 工具不套 `tool_guard`，仅用 `@tool`，并在函数体内 try/except 返回错误文本。以实证为准。）

- [ ] **Step 3: build_agent + chat 接线**

`build_agent` 签名 → `build_agent(thread_id, checkpointer=None, skill_rows=None, kb_ids=None, user_id=None)`；工具列表构造：
```python
    tools = [web_search, fetch_page, stock_quote, stock_financials, make_run_python(ws)]
    if kb_ids and user_id is not None:
        from app.agent.tools.kb import make_kb_search
        from app.core.db import get_sessionmaker
        tools.append(make_kb_search(get_sessionmaker(), user_id, kb_ids))
    return create_deep_agent(model=_make_model(), tools=tools, ...)
```
`chat/router.py`：解析 `mounted_kb_ids`（str→UUID，非法忽略），传 `kb_ids` + `user_id=user.id`：
```python
    mounted = []
    for x in (request.mounted_kb_ids or []):
        try:
            mounted.append(uuid.UUID(x))
        except ValueError:
            pass
    agent = build_agent(thread_id, checkpointer, skill_rows=skill_rows, kb_ids=mounted, user_id=user.id)
```
`chat/schemas.py` `ChatRequest` 加 `mounted_kb_ids: list[str] | None = Field(default=None, alias="mountedKbIds")`。

- [ ] **Step 4: 测试**

`backend/tests/test_kb_retrieval.py`:
```python
import uuid

import pytest

from app.auth.models import User
from app.core.security import hash_password
from app.kb.ingest import ingest_document
from app.kb.models import Kb, KbDocument, KbSubscription
from app.kb.retrieval import accessible_kb_ids, search_chunks


async def _kb_with_doc(db, owner, name, text):
    kb = Kb(owner_id=owner.id, name=name)
    db.add(kb)
    await db.flush()
    doc = KbDocument(kb_id=kb.id, filename=f"{name}.txt", status="pending")
    db.add(doc)
    await db.commit()
    await ingest_document(doc.id, doc.filename, text.encode("utf-8"))
    return kb


@pytest.mark.asyncio
async def test_search_returns_sourced_hits(db_session):
    u = User(email=f"r-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add(u)
    await db_session.flush()
    kb = await _kb_with_doc(db_session, u, "研报", "贵州茅台2025年报净利润增长强劲。")
    hits = await search_chunks(db_session, [kb.id], "茅台 净利润")
    assert hits and hits[0]["filename"] == "研报.txt" and "kb_id" in hits[0]


@pytest.mark.asyncio
async def test_accessible_filters_unowned_and_unshared(db_session):
    a = User(email=f"a-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    b = User(email=f"b-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add_all([a, b])
    await db_session.flush()
    kb_a = Kb(owner_id=a.id, name="A私有")
    db_session.add(kb_a)
    await db_session.flush()
    # b 请求 a 的私有库 → 不可见
    assert await accessible_kb_ids(db_session, b.id, [kb_a.id]) == []
    # a 自己可见
    assert await accessible_kb_ids(db_session, a.id, [kb_a.id]) == [kb_a.id]
    # b 订阅但 a 未共享 → 仍不可见
    db_session.add(KbSubscription(kb_id=kb_a.id, user_id=b.id))
    await db_session.commit()
    assert await accessible_kb_ids(db_session, b.id, [kb_a.id]) == []
```

- [ ] **Step 5: 全量回归 + Commit**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_kb_retrieval.py -q && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q`
Expected: 全绿（chat 回归：mounted_kb_ids 缺省=None → 不挂 kb 工具，行为不变）

```bash
git add backend/app/kb/retrieval.py backend/app/agent/tools/kb.py backend/app/agent/build.py backend/app/chat/ backend/tests/test_kb_retrieval.py
git commit -m "feat(kb): retrieval service, kb_search agent tool, chat mounting"
```

---

### Task 7: 共享 / 订阅

**Files:**
- Modify: `backend/app/kb/router.py`（分享/撤销/订阅端点）
- Test: `backend/tests/test_kb_sharing.py`

**Interfaces:**
- Produces:
  - `POST /api/kb/{id}/share` → 生成随机 `share_slug`（16 hex）+ `is_shared=True` → `{share_slug}`（非本人 404；已分享则返回现有 slug）
  - `DELETE /api/kb/{id}/share` → `is_shared=False`（保留 slug 但失效——检索按 is_shared 门控）→ `{shared: false}`
  - `POST /api/kb/subscribe/{share_slug}` → 找 is_shared 的 KB → 建订阅（幂等）→ `{kb_id,name}`（无效/未共享 slug 404；不能订阅自己的库 → 400）
  - `GET /api/kb/subscribed` → 已订阅且仍共享的 KB `[{id,name}]`

- [ ] **Step 1: 端点**

`backend/app/kb/router.py` 追加（复用既有 imports + `secrets`）:
```python
import secrets

from app.kb.models import KbSubscription


@router.post("/{kb_id}/share")
async def share_kb(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await _owned_kb(db, user, kb_id)
    if not kb.share_slug:
        kb.share_slug = secrets.token_hex(8)
    kb.is_shared = True
    await db.commit()
    return {"share_slug": kb.share_slug}


@router.delete("/{kb_id}/share")
async def unshare_kb(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await _owned_kb(db, user, kb_id)
    kb.is_shared = False
    await db.commit()
    return {"shared": False}


@router.post("/subscribe/{share_slug}")
async def subscribe_kb(share_slug: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = (await db.execute(
        select(Kb).where(Kb.share_slug == share_slug, Kb.is_shared.is_(True))
    )).scalar_one_or_none()
    if kb is None:
        raise HTTPException(404, "分享不存在或已关闭")
    if kb.owner_id == user.id:
        raise HTTPException(400, "不能订阅自己的知识库")
    exists = (await db.execute(
        select(KbSubscription).where(KbSubscription.kb_id == kb.id, KbSubscription.user_id == user.id)
    )).scalar_one_or_none()
    if exists is None:
        db.add(KbSubscription(kb_id=kb.id, user_id=user.id))
        await db.commit()
    return {"kb_id": str(kb.id), "name": kb.name}


@router.get("/subscribed", response_model=list[dict])
async def subscribed_kb(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kbs = (await db.execute(
        select(Kb).join(KbSubscription, KbSubscription.kb_id == Kb.id)
        .where(KbSubscription.user_id == user.id, Kb.is_shared.is_(True)).order_by(Kb.name)
    )).scalars().all()
    return [{"id": str(k.id), "name": k.name} for k in kbs]
```
**路由顺序注意**：`/subscribe/{share_slug}` 与 `/subscribed` 都以 `/sub` 开头，且 `/{kb_id}/...` 是路径参数——把 `/subscribed`、`/subscribe/{slug}` 定义在 `/{kb_id}` 相关路由**之前**，避免 `subscribed` 被当作 kb_id 匹配。Read 现有路由顺序并调整定义次序（FastAPI 按定义序匹配）。

- [ ] **Step 2: 测试**

`backend/tests/test_kb_sharing.py`:
```python
import uuid

import pytest

from app.auth.models import User
from app.core.security import hash_password
from app.kb.models import Kb
from app.kb.retrieval import accessible_kb_ids


@pytest.mark.asyncio
async def test_share_subscribe_and_revoke(client, db_session, registered_user):
    owner_h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "共享库"}, headers=owner_h)).json()["id"]
    slug = (await client.post(f"/api/kb/{kb_id}/share", headers=owner_h)).json()["share_slug"]

    # 另一个用户订阅
    other = User(email=f"o-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add(other)
    await db_session.commit()
    oh = _auth(other)
    sub = await client.post(f"/api/kb/subscribe/{slug}", headers=oh)
    assert sub.status_code == 200 and sub.json()["kb_id"] == kb_id
    assert any(k["id"] == kb_id for k in (await client.get("/api/kb/subscribed", headers=oh)).json())
    assert await accessible_kb_ids(db_session, other.id, [uuid.UUID(kb_id)]) == [uuid.UUID(kb_id)]

    # owner 撤销共享 → 订阅失效
    await client.delete(f"/api/kb/{kb_id}/share", headers=owner_h)
    assert await accessible_kb_ids(db_session, other.id, [uuid.UUID(kb_id)]) == []
    assert (await client.get("/api/kb/subscribed", headers=oh)).json() == []


@pytest.mark.asyncio
async def test_cannot_subscribe_own_and_bad_slug(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "自有"}, headers=h)).json()["id"]
    slug = (await client.post(f"/api/kb/{kb_id}/share", headers=h)).json()["share_slug"]
    assert (await client.post(f"/api/kb/subscribe/{slug}", headers=h)).status_code == 400
    assert (await client.post("/api/kb/subscribe/deadbeef", headers=h)).status_code == 404
```

- [ ] **Step 3: 跑测试 + Commit**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_kb_sharing.py -q`
Expected: 2 passed

```bash
git add backend/app/kb/router.py backend/tests/test_kb_sharing.py
git commit -m "feat(kb): share link, subscribe, revoke with retrieval gating"
```

---

### Task 8: 前端知识库页 + 聊天挂载选择器

**Files:**
- Create: `frontend/src/lib/kb.ts`、`frontend/src/pages/KbPage.tsx`
- Modify: 路由 + 侧栏导航、聊天页（挂载多选 → 随消息发送）
- Test: `frontend/src/lib/kb.test.ts`

**Interfaces:**
- Consumes: `apiFetch`、KB API（T5/T7）。
- Produces:
  - `fetchKbs()`、`createKb(name)`、`uploadDoc(kbId, file)`、`fetchDocs(kbId)`、`shareKb(kbId)`、`subscribeKb(slug)`、`fetchSubscribed()`（均 apiFetch）
  - 路由 `/kb`（RequireAuth）；侧栏「知识库」入口 `data-testid="nav-kb"`
  - KbPage：建库、上传（file input）、文档列表 + 状态徽标（轮询直到 ready/failed）、生成分享链接、订阅输入框
  - 聊天页：一个 KB 多选器（自有 + 已订阅），选中的 `kbId` 数组随每条消息以 `mountedKbIds` 放入 assistant-transport body（Read `RuntimeProvider` 现有 body 注入 threadId 的位置，追加 mountedKbIds；选择存 zustand/localStorage，`data-testid="kb-mount-{id}"`）

- [ ] **Step 1: API 封装 + 测试**

`frontend/src/lib/kb.ts`（镜像 `skills.ts` 模式；上传用 `FormData`，apiFetch 需支持传 body/method——Read `api.ts` 确认 apiFetch 透传 init）:
```ts
import { apiFetch } from "./api";

export type Kb = { id: string; name: string; is_shared: boolean; doc_count: number };
export type KbDoc = { id: string; filename: string; status: string; chunk_count: number; error: string | null };

export async function fetchKbs(): Promise<Kb[]> {
  const r = await apiFetch("/api/kb");
  if (!r.ok) throw new Error("failed");
  return r.json();
}
export async function createKb(name: string): Promise<Kb> {
  const r = await apiFetch("/api/kb", { method: "POST", body: JSON.stringify({ name }), headers: { "Content-Type": "application/json" } });
  if (!r.ok) throw new Error("failed");
  return r.json();
}
export async function uploadDoc(kbId: string, file: File): Promise<void> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await apiFetch(`/api/kb/${kbId}/documents`, { method: "POST", body: fd });
  if (!r.ok) throw new Error("upload failed");
}
export async function fetchDocs(kbId: string): Promise<KbDoc[]> {
  const r = await apiFetch(`/api/kb/${kbId}/documents`);
  if (!r.ok) throw new Error("failed");
  return r.json();
}
export async function shareKb(kbId: string): Promise<{ share_slug: string }> {
  const r = await apiFetch(`/api/kb/${kbId}/share`, { method: "POST" });
  if (!r.ok) throw new Error("failed");
  return r.json();
}
export async function subscribeKb(slug: string): Promise<{ kb_id: string; name: string }> {
  const r = await apiFetch(`/api/kb/subscribe/${slug}`, { method: "POST" });
  if (!r.ok) throw new Error("failed");
  return r.json();
}
export async function fetchSubscribed(): Promise<{ id: string; name: string }[]> {
  const r = await apiFetch("/api/kb/subscribed");
  if (!r.ok) throw new Error("failed");
  return r.json();
}
```
`kb.test.ts`（vitest，mock apiFetch）：断言 `fetchKbs` 解析列表 + `createKb` POST 到 `/api/kb`。

- [ ] **Step 2: KbPage + 挂载选择器 + 路由/导航**

- `KbPage.tsx`：`useQuery(["kb"], fetchKbs)` 列表 + 建库输入；每个 KB 卡片：上传按钮（`<input type=file>` → `uploadDoc` → invalidate）、文档列表（`useQuery(["kb-docs", id], ...)`，pending/processing 时 `refetchInterval: 1500`，状态徽标）、分享按钮（→ 显示 slug）、订阅输入框（slug → `subscribeKb`）。元素 `data-testid`：`kb-create`、`kb-upload-{id}`、`kb-share-{id}`、`kb-subscribe`。
- 路由 `/kb`（RequireAuth，同 ChatPage）；侧栏加「知识库」链接 `data-testid="nav-kb"`。
- 聊天挂载：读 `frontend/src/chat/RuntimeProvider.tsx` 里 `body` 注入 `threadId` 的位置，追加 `mountedKbIds`（来自一个 zustand store 或 localStorage 的选中数组）。聊天页顶部/侧加一个多选（自有+已订阅 KB），`data-testid="kb-mount-{id}"`。选择随每条消息发送。

- [ ] **Step 3: 验证 + Commit**

Run: `cd frontend && npx vitest run && npm run build`
Expected: 全绿 + 构建成功

手工冒烟（dev postgres 5434，后端 `EMBEDDING_BACKEND=fake FAKE_LLM=1`）：登录 → /kb 建库 → 上传 txt → 状态转 ready → 生成分享 slug → 回聊天挂载该库 → 发消息（fake 模型不必真检索，验证 mountedKbIds 进入请求体即可，可用浏览器网络面板确认）。贴观察。

```bash
git add frontend/src/
git commit -m "feat(frontend): knowledge base page and chat mount selector"
```

---

### Task 9: 集成闭环 + README

**Files:**
- Create: `backend/tests/test_kb_flow.py`
- Modify: `backend/README.md`（「知识库 RAG（计划 5）」一节）
- Modify: `frontend/e2e/chat.spec.ts`（KB 页冒烟，best-effort）

**Interfaces:**
- 串起 T4/T5/T6/T7：上传→ready→检索命中带出处；订阅他人共享库→检索可及；撤销→不可及。

- [ ] **Step 1: 集成测试**

`backend/tests/test_kb_flow.py`:
```python
import io
import uuid

import pytest

from app.kb.retrieval import accessible_kb_ids, search_chunks


@pytest.mark.asyncio
async def test_upload_then_retrieve_with_source(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "研报"}, headers=h)).json()["id"]
    files = {"file": ("maotai.txt", io.BytesIO("贵州茅台2025年净利润大幅增长。".encode("utf-8")), "text/plain")}
    await client.post(f"/api/kb/{kb_id}/documents", files=files, headers=h)
    import asyncio
    for _ in range(50):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if docs and docs[0]["status"] in ("ready", "failed"):
            break
        await asyncio.sleep(0.1)
    assert docs[0]["status"] == "ready"
    hits = await search_chunks(db_session, [uuid.UUID(kb_id)], "茅台 净利润")
    assert hits and hits[0]["filename"] == "maotai.txt"
```

- [ ] **Step 2: e2e（best-effort）**

`frontend/e2e/chat.spec.ts` 追加：登录 → 点 `[data-testid="nav-kb"]` → 断言建库输入 `[data-testid="kb-create"]` 可见。跑 `npx playwright test`；flaky 超出 selector 微调则回退并注明（后端集成测试为必交付）。

- [ ] **Step 3: README + 全量回归 + Commit**

`backend/README.md` 补「知识库 RAG（计划 5）」：provider 抽象（fake/siliconflow，env `EMBEDDING_BACKEND`/`SILICONFLOW_API_KEY`）、pgvector + HNSW、上传→异步摄取状态机、检索（向量 top-20→rerank top-5→出处）、挂载（`mountedKbIds`）、共享/订阅、上传限制（10MB、txt/md/pdf）。

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q && cd ../frontend && npx vitest run`
Expected: 全绿

```bash
git add backend/tests/test_kb_flow.py backend/README.md frontend/e2e/
git commit -m "test(kb): rag flow integration and README"
```

---

## Self-Review 记录

**1. Spec 覆盖（§5）**：
- 模型 kb/kb_documents（状态机 pending/processing/ready/failed）/kb_chunks（切片+BGE-M3 向量+HNSW）/kb_subscriptions（只读引用不复制）→ Task 1 ✅。
- 上传→解析→切片→向量化→入库 → Task 3/4/5 ✅；状态机 → Task 4 ✅。
- 检索 kb_search 作为 agent 工具；用户选择挂载 KB（自有+已订阅）；向量 top-20→reranker top-5→带出处 → Task 6 ✅；不做独立问答页，聊天唯一入口 → 挂载选择器 + kb_search 工具，无问答页 ✅。
- 共享：详情页生成随机 slug → 订阅；owner 关闭共享订阅失效；只读全库共享 → Task 7 ✅。
- **偏差**：embedding/reranker 用 SiliconFlow 托管 BGE（用户决策"外部 API"），非本地部署——模型选型仍是 spec 的 BGE-M3/BGE-reranker-v2-m3，仅运行位置不同；记延后清单（本地化部署选项）。

**2. 占位符扫描**：无 TBD/空壳。Task 6 Step 2 `tool_guard` async 兼容性、Task 5 BackgroundTasks 在 ASGITransport 执行性均为**显式实证点**（带兜底：不兼容则直连 ingest / 工具体内 try-except），非未完成项。前端 Task 8 给结构+验收+testid（与计划 2b/3/4 同粒度）。

**3. 类型一致性**：`Kb/KbDocument/KbChunk/KbSubscription`（T1）全程一致；`get_embedding_provider/get_reranker`（T2）在 T4/T6 一致；`parse_document/chunk_text`（T3）在 T4 一致；`ingest_document`（T4）在 T5/T6/T9 一致；`accessible_kb_ids/search_chunks`（T6）在 T7/T9 一致；`make_kb_search`（T6）；`build_agent(thread_id, checkpointer=None, skill_rows=None, kb_ids=None, user_id=None)` T6 定义 chat 消费一致；`mounted_kb_ids`/`mountedKbIds` 前后端一致。

**本计划显式延后（记 ledger）**：
- 本地化 BGE 部署选项（当前 SiliconFlow API）。
- KB 检索计费（当前只读免费；如需按检索/token 计费归后续）。
- 增量重摄取/文档级删除（当前删 KB 级联；单文档删除可后补）。
- BackgroundTasks 换持久任务队列（进程重启丢失在途摄取；生产可换 Celery/APScheduler 持久化，归部署计划）。
- 更丰富解析（docx/html/表格）；当前 txt/md/pdf。
- 细粒度共享权限（当前只读全库）。
