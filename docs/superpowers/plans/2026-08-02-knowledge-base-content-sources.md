# 知识库内容源接入 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让平台自己抓来的微信公众号文章和 7x24 快讯能进知识库（单篇加入、整号订阅、批量加入），并把 KB 面板重写为「库列表 → 内容索引 → 详情 + 对话栏」三级浏览。

**Architecture:** 在现有 `app/kb/` 上加一层「来源解析」间接层：每种来源实现 describe（快，只读本地库）与 resolve（慢，可能走网络）两个函数，统一经 `add_source_item()` 建 `KbDocument(status="pending")` 后把正文抓取与切片丢后台。切片逻辑从 `ingest_document` 里剥出 `ingest_text`，三条来源共用同一套切片/向量复用/状态机。前端把 249 行的 `KbPanel.tsx` 按栏拆成 5 个组件。

**Tech Stack:** FastAPI + SQLAlchemy 2.x async + Alembic + pgvector；pytest + testcontainers(pgvector/pgvector:pg16)；React 19 + TanStack Query + zustand + vitest。

## 与 spec 的两处偏差

实现前请先读这一节，它修正了 spec 中与现有代码不符的地方。

1. **spec 第 186 行「凭证池为空时整批暂停」不成立。** `fetch_article_text()`（`backend/app/social/wechat/client.py:78`）只是对文章 URL 发普通 GET，不带 cookie/token；凭证池只用于 `searchbiz` / `appmsgpublish` 两个列表接口。所以正文抓取没有「凭证池」这个概念可挂。限流器仍然要做（微信对文章页本身有风控），但整批中止条件改为 **连续失败 3 篇即中止本批**，保住 spec 的原意：不让一次回填把几十篇全标脏。见 Task 6。

2. **详情页要展示「入库时的文本快照」（spec 第 277 行），需要一个存储位置。** `chunk_text()` 相邻片段有 100 字符重叠，从 `kb_chunks` 拼不回原文。因此给 `kb_documents` 加一列 `text: str | None` 存入库文本，详情端点直接返回它。见 Task 1、Task 3。

另有一处收紧：向量复用的缓存键用 `f"{backend}:{model}"`（如 `fake:BAAI/bge-m3`），而非 spec 第 87 行的裸 `embedding_model`。否则本地以 `EMBEDDING_BACKEND=fake` 跑出的假向量，会在切到 siliconflow 后被真索引复用，污染检索结果——两者 `embedding_model` 配置值相同，光靠模型名区分不开。见 Task 2。

## Global Constraints

- 后端命令一律在 `backend/` 下用 `uv run` 前缀执行（如 `uv run pytest`）。
- 前端命令在 `frontend/` 下执行；单测 `npx vitest run <path>`，类型检查 `npx tsc -b`，lint `npm run lint`。
- Python line-length 100（`[tool.ruff]`）。提交前跑 `uv run ruff check .`。
- 测试跑在 testcontainers 起的 `pgvector/pgvector:pg16` 上，session 级 fixture 自动建库并 `alembic upgrade head`；**DB 跨用例不回滚**，故每个用例造数据必须用 `uuid.uuid4()` 保证邮箱/外部 id 唯一（现有测试全都这么做）。
- `EMBEDDING_BACKEND` 默认 `fake`，测试不得依赖真实 embedding API。
- `EMBEDDING_DIM = 1024`，写死在 `app/kb/models.py`。
- 新增配置项一律加到 `app/core/config.py` 的 `Settings` 类，带默认值；测试中改配置后要 `config.get_settings.cache_clear()`（`get_settings` 有 `@lru_cache`）。
- 迁移文件放 `backend/alembic/versions/`，`down_revision` 必须指向当时的 head。**当前 head 是 `7e2c0713f82d`**；本计划的迁移在 Task 1 一次性完成，后续任务不再加迁移。
- 所有新端点挂在现有 `/api/kb` 前缀下，鉴权走 `_owned_kb`（仅自有库，订阅的共享库不进 KB 面板）。
- 新路由的定义顺序：**静态路径段必须写在 `/{kb_id}` 之前**，否则被当作路径参数捕获（`app/kb/router.py:53` 已有此坑的注释）。
- 中文注释与错误文案，与现有代码一致。

---

## 文件结构

**后端**

| 文件 | 职责 |
|---|---|
| `app/kb/models.py`（改） | 加 `KbSource` 表；`KbDocument` 加 7 列；`KbChunk` 加 2 列 |
| `app/kb/sources.py`（新） | 来源解析层：`SourceMeta` + describe/resolve 注册表 |
| `app/kb/service.py`（新） | `add_source_item()`、配额检查。请求内的业务逻辑，不含 HTTP |
| `app/kb/ingest.py`（改） | 剥出 `ingest_text()`；加 `ingest_source_document()` 后台任务 |
| `app/kb/embedding_cache.py`（新） | 向量复用：按 `(content_hash, embedding_model)` 查已有向量 |
| `app/kb/ratelimit.py`（新） | 进程内正文抓取限流器（信号量 + 最小间隔），前后台共用 |
| `app/kb/backfill.py`（新） | 整号订阅的回填任务 + poll 增量钩子 |
| `app/kb/schemas.py`（改） | 新增请求/响应模型 |
| `app/kb/router.py`（改） | 新增 6 个端点，扩展 2 个 |
| `app/social/ingest.py`（改） | `ingest_account()` 返回值从 `int` 改为新增文章 id 列表 |
| `app/social/router.py`（改） | `refresh` 端点适配返回值变化 |
| `app/social/job.py`（改） | `poll_all_subscriptions` 适配 + 调 KB 增量钩子 |
| `app/core/config.py`（改） | 5 个新配置项 |

拆 `service.py` 与 `ingest.py` 的理由：前者跑在请求里（快、要事务）、后者跑在后台任务里（慢、自己开 session），混在一个文件里很容易误用错的 session。

**前端**

| 文件 | 职责 |
|---|---|
| `src/lib/kb.ts`（改） | 扩展类型与 API 封装 |
| `src/panels/KbPanel.tsx`（重写） | 容器：三栏布局 + 选中态 + 折叠态 |
| `src/panels/kb/KbList.tsx`（新） | 库列表、新建、分享、订阅 |
| `src/panels/kb/KbDocumentIndex.tsx`（新） | 内容索引：倒序列表、来源图标、删除 |
| `src/panels/kb/KbDocumentDetail.tsx`（新） | 详情：元信息 + 入库文本快照 |
| `src/panels/kb/KbAssistant.tsx`（新） | 可折叠对话栏，锁定挂载当前库 |
| `src/components/AddToKbDialog.tsx`（新） | 四处复用的「加入知识库」弹窗 |
| `src/chat/RuntimeProvider.tsx`（改） | 加可选 prop `mountedKbIds` 覆盖全局 store |
| `src/panels/SocialPanel.tsx`（改） | 三个加入入口 |
| `src/panels/NewsAssistant.tsx`（改） | 批量加入入口 |

---

## Task 1: 数据模型与迁移

**Files:**
- Modify: `backend/app/kb/models.py`
- Create: `backend/alembic/versions/a3b4c5d6e7f8_kb_content_sources.py`
- Modify: `backend/app/threads/models.py`
- Test: `backend/tests/test_kb_models.py`（扩展）

**Interfaces:**
- Produces:
  - `KbDocument` 新字段：`title: str`、`filename: str | None`、`text: str | None`、`source_type: str`、`source_ref_id: str | None`、`source_url: str | None`、`published_at: dt.datetime | None`、`kb_source_id: uuid.UUID | None`
  - `KbDocument.__table_args__` 含 `UniqueConstraint("kb_id", "source_type", "source_ref_id", name="uq_kb_doc_source")`
  - `KbChunk` 新字段：`content_hash: str`、`embedding_model: str`（均 NOT NULL、建索引）
  - `KbSource` 模型，字段见下方代码
  - `Thread.ref_id: uuid.UUID | None`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_kb_models.py` 末尾追加：

```python
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
```

文件顶部的 import 需补 `func`、`select`（现有文件只在函数内 import 过 `select`）。把首行 import 改成：

```python
import uuid

import pytest
from sqlalchemy import func, select

from app.auth.models import User
from app.core.security import hash_password
from app.kb.models import Kb, KbChunk, KbDocument
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_kb_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'KbSource' from 'app.kb.models'`

- [ ] **Step 3: 改模型**

`backend/app/kb/models.py`——`KbDocument` 整个类替换为：

```python
class KbDocument(Base):
    __tablename__ = "kb_documents"
    __table_args__ = (
        UniqueConstraint("kb_id", "source_type", "source_ref_id", name="uq_kb_doc_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    # 仅上传文档有值；社媒/快讯为 NULL
    filename: Mapped[str | None] = mapped_column(String(255))
    # 入库时的文本快照。详情页展示它而非回源重抓——检索命中的就是这份文本，
    # 展示与检索必须一致（chunk 间有重叠，拼不回原文，故单独存一份）。
    text: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="upload", server_default="upload", index=True
    )
    # 源表主键（字符串化的 uuid）。upload 为 NULL，借 Postgres「NULL 互不相等」
    # 绕过唯一约束，同名文件仍可重复上传。
    source_ref_id: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(String(1024))
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    kb_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("kb_sources.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

`KbChunk` 的 `content` 之后插入两列：

```python
    # 向量复用键：同一文本在任何库里只需算一次 embedding。见 embedding_cache.py。
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
```

在 `KbDocument` **之前**（`kb_documents` 有 FK 指向它，SQLAlchemy 按名字解析不强求顺序，但读起来顺）插入新表：

```python
class KbSource(Base):
    """知识库订阅的内容源。当前仅 wechat_account，未来可扩 xhs_user 等。"""

    __tablename__ = "kb_sources"
    __table_args__ = (
        UniqueConstraint("kb_id", "source_type", "source_ref_id", name="uq_kb_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # 冗余存一份显示名，列订阅时免 join 源表
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # pending / syncing / ready / failed / limited
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

`backend/app/threads/models.py` 的 `Thread` 类末尾加一列：

```python
    # type="kb" 时指向 kb.id（每库一个常驻会话）；type="news"/"chat" 为 NULL
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
```

该文件的 import 需补 `UUID`：把 `from sqlalchemy.dialects.postgresql import UUID` 保留（已有），无需改动。

- [ ] **Step 4: 写迁移**

`backend/alembic/versions/a3b4c5d6e7f8_kb_content_sources.py`：

```python
"""kb_content_sources

Revision ID: a3b4c5d6e7f8
Revises: 7e2c0713f82d
Create Date: 2026-08-02 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, Sequence[str], None] = '7e2c0713f82d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'kb_sources',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('kb_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_type', sa.String(length=32), nullable=False),
        sa.Column('source_ref_id', sa.String(length=128), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['kb_id'], ['kb.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('kb_id', 'source_type', 'source_ref_id', name='uq_kb_source'),
    )
    op.create_index(op.f('ix_kb_sources_kb_id'), 'kb_sources', ['kb_id'])
    op.create_index(op.f('ix_kb_sources_source_ref_id'), 'kb_sources', ['source_ref_id'])

    # --- kb_documents 扩展 ---
    op.add_column('kb_documents', sa.Column('title', sa.String(length=512), nullable=True))
    op.add_column('kb_documents', sa.Column('text', sa.Text(), nullable=True))
    op.add_column('kb_documents', sa.Column(
        'source_type', sa.String(length=32), nullable=False, server_default='upload'))
    op.add_column('kb_documents', sa.Column('source_ref_id', sa.String(length=128), nullable=True))
    op.add_column('kb_documents', sa.Column('source_url', sa.String(length=1024), nullable=True))
    op.add_column('kb_documents', sa.Column(
        'published_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('kb_documents', sa.Column(
        'kb_source_id', postgresql.UUID(as_uuid=True), nullable=True))
    # 存量行：title 回填为 filename，然后置 NOT NULL；filename 放宽为可空
    op.execute('UPDATE kb_documents SET title = filename WHERE title IS NULL')
    op.alter_column('kb_documents', 'title', nullable=False)
    op.alter_column('kb_documents', 'filename', existing_type=sa.String(length=255), nullable=True)
    op.create_foreign_key('fk_kb_documents_kb_source', 'kb_documents', 'kb_sources',
                          ['kb_source_id'], ['id'], ondelete='SET NULL')
    op.create_index(op.f('ix_kb_documents_source_type'), 'kb_documents', ['source_type'])
    op.create_index(op.f('ix_kb_documents_published_at'), 'kb_documents', ['published_at'])
    op.create_index(op.f('ix_kb_documents_kb_source_id'), 'kb_documents', ['kb_source_id'])
    op.create_unique_constraint('uq_kb_doc_source', 'kb_documents',
                               ['kb_id', 'source_type', 'source_ref_id'])

    # --- kb_chunks 扩展（向量复用键）---
    op.add_column('kb_chunks', sa.Column('content_hash', sa.String(length=64), nullable=True))
    op.add_column('kb_chunks', sa.Column('embedding_model', sa.String(length=128), nullable=True))
    # 存量行：hash 由 content 现算（pgcrypto 不一定装，用 sha256 内置函数）；
    # 模型名填 'legacy'——存量向量的真实模型无从考证，标记为 legacy 使其永不被复用，
    # 比错填当前模型名安全（错填会让旧模型向量污染新索引）。
    op.execute("UPDATE kb_chunks SET content_hash = encode(sha256(content::bytea), 'hex') "
               "WHERE content_hash IS NULL")
    op.execute("UPDATE kb_chunks SET embedding_model = 'legacy' WHERE embedding_model IS NULL")
    op.alter_column('kb_chunks', 'content_hash',
                    existing_type=sa.String(length=64), nullable=False)
    op.alter_column('kb_chunks', 'embedding_model',
                    existing_type=sa.String(length=128), nullable=False)
    op.create_index(op.f('ix_kb_chunks_content_hash'), 'kb_chunks', ['content_hash'])
    op.create_index(op.f('ix_kb_chunks_embedding_model'), 'kb_chunks', ['embedding_model'])

    # --- threads.ref_id ---
    op.add_column('threads', sa.Column('ref_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f('ix_threads_ref_id'), 'threads', ['ref_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_threads_ref_id'), table_name='threads')
    op.drop_column('threads', 'ref_id')

    op.drop_index(op.f('ix_kb_chunks_embedding_model'), table_name='kb_chunks')
    op.drop_index(op.f('ix_kb_chunks_content_hash'), table_name='kb_chunks')
    op.drop_column('kb_chunks', 'embedding_model')
    op.drop_column('kb_chunks', 'content_hash')

    op.drop_constraint('uq_kb_doc_source', 'kb_documents', type_='unique')
    op.drop_index(op.f('ix_kb_documents_kb_source_id'), table_name='kb_documents')
    op.drop_index(op.f('ix_kb_documents_published_at'), table_name='kb_documents')
    op.drop_index(op.f('ix_kb_documents_source_type'), table_name='kb_documents')
    op.drop_constraint('fk_kb_documents_kb_source', 'kb_documents', type_='foreignkey')
    op.execute('UPDATE kb_documents SET filename = title WHERE filename IS NULL')
    op.alter_column('kb_documents', 'filename', existing_type=sa.String(length=255), nullable=False)
    for col in ('kb_source_id', 'published_at', 'source_url',
                'source_ref_id', 'source_type', 'text', 'title'):
        op.drop_column('kb_documents', col)

    op.drop_index(op.f('ix_kb_sources_source_ref_id'), table_name='kb_sources')
    op.drop_index(op.f('ix_kb_sources_kb_id'), table_name='kb_sources')
    op.drop_table('kb_sources')
```

注意 `sha256()` 是 PG 11+ 内置函数，不需要 pgcrypto 扩展。

- [ ] **Step 5: 修补现有代码里 KbDocument 的构造点**

`title` 是 NOT NULL，现有两处构造 `KbDocument` 只传了 `filename`，会在插入时报错。

`backend/app/kb/router.py:112` 改为：

```python
    doc = KbDocument(kb_id=kb.id, title=file.filename or "unnamed",
                     filename=file.filename or "unnamed",
                     source_type="upload", status="pending")
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_kb_models.py -v`
Expected: PASS（5 个用例：原有 2 个 + 新增 3 个）

再跑既有 kb 测试确认迁移没搞坏什么。测试里造 `KbDocument` 的地方也要补 `title`：`tests/test_kb_ingest.py:19`、`tests/test_kb_retrieval.py:16`、`tests/test_kb_models.py:18/36`——把 `KbDocument(kb_id=..., filename=X, ...)` 补成 `KbDocument(kb_id=..., title=X, filename=X, ...)`。

Run: `cd backend && uv run pytest tests/test_kb_models.py tests/test_kb_ingest.py tests/test_kb_retrieval.py tests/test_kb_api.py tests/test_kb_flow.py -v`
Expected: 全 PASS

- [ ] **Step 7: 提交**

```bash
cd backend && uv run ruff check app tests
git add app/kb/models.py app/kb/router.py app/threads/models.py \
        alembic/versions/a3b4c5d6e7f8_kb_content_sources.py tests/test_kb_models.py \
        tests/test_kb_ingest.py tests/test_kb_retrieval.py
git commit -m "feat(kb): 内容源数据模型 — kb_sources 表、文档来源字段、向量复用键"
```

## Task 2: 向量复用

同一段文本在任何库里只算一次 embedding。不建独立缓存表——复用 `kb_chunks` 意味着不需要清理策略，最后一个引用该文本的 chunk 被删时「缓存」自动消失。

**Files:**
- Create: `backend/app/kb/embedding_cache.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_kb_embedding_cache.py`

**Interfaces:**
- Consumes: Task 1 的 `KbChunk.content_hash` / `KbChunk.embedding_model`
- Produces:
  - `content_hash(text: str) -> str` — sha256 十六进制
  - `current_embedding_model() -> str` — 返回 `f"{backend}:{model}"`，如 `"fake:BAAI/bge-m3"`
  - `async embed_with_cache(db: AsyncSession, texts: list[str]) -> list[list[float]]` — 返回与 `texts` 等长、同序的向量；命中缓存的不调 provider

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_kb_embedding_cache.py`：

```python
import uuid

import pytest
from sqlalchemy import select

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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_kb_embedding_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.kb.embedding_cache'`

- [ ] **Step 3: 实现**

创建 `backend/app/kb/embedding_cache.py`：

```python
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
```

- [ ] **Step 4: 加配置项**

`backend/app/core/config.py` 的 `kb_max_upload_mb` 之后插入：

```python
    kb_backfill_delay_seconds: float = 2.0     # 正文抓取最小间隔（前后台共用限流器）
    kb_backfill_max_failures: int = 3          # 连续失败几篇后中止本批回填
    kb_max_documents_per_kb: int = 2000        # 单库文档数上限（含上传），admin 豁免
    kb_max_sources_per_user: int = 10          # 每用户订阅源总数上限，admin 豁免
    kb_backfill_batch_limit: int = 50          # 单次回填最多处理多少篇
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_kb_embedding_cache.py -v`
Expected: PASS（7 个用例）

- [ ] **Step 6: 提交**

```bash
cd backend && uv run ruff check app tests
git add app/kb/embedding_cache.py app/core/config.py tests/test_kb_embedding_cache.py
git commit -m "feat(kb): 向量复用 — 相同文本跨库不重复调 embedding API"
```

---

## Task 3: 来源解析层与 ingest_text 重构

把「内容从哪来」和「怎么入库」切开。describe 只读本地库（快，跑在请求里），resolve 产出正文（慢，可能走网络，只在后台任务里调）。

**Files:**
- Create: `backend/app/kb/sources.py`
- Modify: `backend/app/kb/ingest.py`
- Test: `backend/tests/test_kb_sources.py`
- Test: `backend/tests/test_kb_ingest.py`（扩展）

**Interfaces:**
- Consumes: Task 2 的 `embed_with_cache()` / `content_hash()` / `current_embedding_model()`
- Produces:
  - `SourceMeta` dataclass：`title: str`、`source_url: str | None`、`published_at: dt.datetime | None`
  - `async describe(db: AsyncSession, source_type: str, source_ref_id: str) -> SourceMeta` — 源不存在时抛 `SourceNotFound`
  - `async resolve_text(db: AsyncSession, source_type: str, source_ref_id: str, http=None) -> str`
  - `class SourceNotFound(Exception)`
  - `SUPPORTED_ITEM_TYPES: frozenset[str]` = `{"wechat_article", "news_item"}`
  - `async ingest_text(document_id: uuid.UUID, text: str) -> None` — 切片 → 查缓存 → 存 chunk → 置 ready；同时把 `text` 写入 `KbDocument.text`
  - `async ingest_document(document_id: uuid.UUID, filename: str, raw: bytes) -> None` — 签名不变

- [ ] **Step 1: 写失败测试（sources）**

创建 `backend/tests/test_kb_sources.py`：

```python
import datetime as dt
import uuid

import httpx
import pytest

from app.auth.models import User  # noqa: F401 — 注册 FK 目标表
from app.kb.sources import (
    SUPPORTED_ITEM_TYPES,
    SourceNotFound,
    describe,
    resolve_text,
)


async def _wechat_article(db, title="茅台年报解读", content=None):
    from app.social.ingest import get_or_create_account
    from app.social.models import WechatArticle

    acc = await get_or_create_account(db, f"F{uuid.uuid4().hex[:8]}", "财经号")
    art = WechatArticle(
        account_id=acc.id, external_id=f"a{uuid.uuid4().hex[:8]}", title=title,
        digest="", cover_url=None, url=f"https://mp.weixin.qq.com/s/{uuid.uuid4().hex[:6]}",
        content=content, published_at=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
    )
    db.add(art)
    await db.commit()
    return art


async def _news_item(db, title, content):
    from app.news.models import NewsItem, NewsSource

    src = NewsSource(name="新浪快讯", type="sina_live", channel="news", config={})
    db.add(src)
    await db.flush()
    item = NewsItem(
        source_id=src.id, channel="news", external_id=f"n{uuid.uuid4().hex[:8]}",
        content_hash=uuid.uuid4().hex, title=title, content=content,
        url="https://finance.sina.com.cn/x", published_at=dt.datetime(2026, 7, 2, tzinfo=dt.UTC),
    )
    db.add(item)
    await db.commit()
    return item


def test_supported_item_types():
    assert SUPPORTED_ITEM_TYPES == frozenset({"wechat_article", "news_item"})


@pytest.mark.asyncio
async def test_describe_wechat_article(db_session):
    art = await _wechat_article(db_session)
    meta = await describe(db_session, "wechat_article", str(art.id))
    assert meta.title == "茅台年报解读"
    assert meta.source_url == art.url
    assert meta.published_at == art.published_at


@pytest.mark.asyncio
async def test_describe_news_item_falls_back_to_content_prefix(db_session):
    """快讯 title 可空，为空时取 content 前 40 字加省略号。"""
    long = "一" * 100
    item = await _news_item(db_session, None, long)
    meta = await describe(db_session, "news_item", str(item.id))
    assert meta.title == "一" * 40 + "…"
    assert meta.published_at == item.published_at


@pytest.mark.asyncio
async def test_describe_news_item_uses_title_when_present(db_session):
    item = await _news_item(db_session, "央行降准", "内容若干")
    meta = await describe(db_session, "news_item", str(item.id))
    assert meta.title == "央行降准"


@pytest.mark.asyncio
async def test_describe_raises_for_missing_and_unknown(db_session):
    with pytest.raises(SourceNotFound):
        await describe(db_session, "wechat_article", str(uuid.uuid4()))
    with pytest.raises(SourceNotFound):
        await describe(db_session, "xhs_note", str(uuid.uuid4()))
    # 非法 uuid 也走同一出口，不该冒 ValueError
    with pytest.raises(SourceNotFound):
        await describe(db_session, "news_item", "not-a-uuid")


@pytest.mark.asyncio
async def test_resolve_news_item_reads_local_no_http(db_session):
    item = await _news_item(db_session, "标题", "快讯正文内容")
    assert await resolve_text(db_session, "news_item", str(item.id)) == "快讯正文内容"


@pytest.mark.asyncio
async def test_resolve_wechat_article_uses_cached_content(db_session):
    art = await _wechat_article(db_session, content="已缓存的正文")
    # 没传 http 也能拿到——正文已在库里，不需要回源
    assert await resolve_text(db_session, "wechat_article", str(art.id)) == "已缓存的正文"


@pytest.mark.asyncio
async def test_resolve_wechat_article_fetches_and_persists(db_session):
    art = await _wechat_article(db_session, content=None)
    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text="<html><body><p>抓来的正文</p></body></html>")
    ))
    text = await resolve_text(db_session, "wechat_article", str(art.id), http=http)
    assert "抓来的正文" in text
    await db_session.refresh(art)
    assert art.content and art.content_fetched_at is not None   # 顺手回填源表
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_kb_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.kb.sources'`

- [ ] **Step 3: 实现 sources.py**

创建 `backend/app/kb/sources.py`：

```python
"""来源解析层：把「内容从哪来」与「怎么入库」切开。

每种来源实现两个函数，按快/慢分工：
  describe    — 只读本地库，跑在请求里，产出建文档行所需的元信息
  resolve     — 产出纯文本正文，只在后台任务里调（可能要回源抓取）

接入新平台只需在两张注册表里各加一项，入库路径不变。
"""
import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

_TITLE_FALLBACK_CHARS = 40


class SourceNotFound(Exception):
    """源记录不存在，或 source_type 不受支持。"""


@dataclass
class SourceMeta:
    title: str
    source_url: str | None
    published_at: dt.datetime | None


def _as_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as e:
        raise SourceNotFound(f"非法的源 id：{raw}") from e


# ---- 微信公众号文章 ----
async def _describe_wechat_article(db: AsyncSession, source_ref_id: str) -> SourceMeta:
    from app.social.models import WechatArticle

    art = await db.get(WechatArticle, _as_uuid(source_ref_id))
    if art is None:
        raise SourceNotFound("公众号文章不存在")
    return SourceMeta(title=art.title, source_url=art.url, published_at=art.published_at)


async def _resolve_wechat_article(db: AsyncSession, source_ref_id: str, http) -> str:
    from app.social.ingest import fetch_article_content
    from app.social.models import WechatArticle

    art = await db.get(WechatArticle, _as_uuid(source_ref_id))
    if art is None:
        raise SourceNotFound("公众号文章不存在")
    if art.content:
        return art.content
    if http is None:
        raise RuntimeError("正文未缓存且未提供 http client")
    # fetch_article_content 顺手把正文写回源表，下次任何库加这篇都不必再抓
    return await fetch_article_content(db, art, http)


# ---- 7x24 快讯 ----
async def _describe_news_item(db: AsyncSession, source_ref_id: str) -> SourceMeta:
    from app.news.models import NewsItem

    item = await db.get(NewsItem, _as_uuid(source_ref_id))
    if item is None:
        raise SourceNotFound("快讯不存在")
    title = item.title or _prefix_title(item.content)
    return SourceMeta(title=title, source_url=item.url, published_at=item.published_at)


async def _resolve_news_item(db: AsyncSession, source_ref_id: str, http) -> str:
    from app.news.models import NewsItem

    item = await db.get(NewsItem, _as_uuid(source_ref_id))
    if item is None:
        raise SourceNotFound("快讯不存在")
    return item.content


def _prefix_title(content: str) -> str:
    """快讯 title 可空，取正文前 40 字当显示名。"""
    text = (content or "").strip()
    if len(text) <= _TITLE_FALLBACK_CHARS:
        return text or "（空快讯）"
    return text[:_TITLE_FALLBACK_CHARS] + "…"


_DESCRIBERS = {
    "wechat_article": _describe_wechat_article,
    "news_item": _describe_news_item,
}
_RESOLVERS = {
    "wechat_article": _resolve_wechat_article,
    "news_item": _resolve_news_item,
}
SUPPORTED_ITEM_TYPES = frozenset(_DESCRIBERS)


async def describe(db: AsyncSession, source_type: str, source_ref_id: str) -> SourceMeta:
    fn = _DESCRIBERS.get(source_type)
    if fn is None:
        raise SourceNotFound(f"不支持的来源类型：{source_type}")
    return await fn(db, source_ref_id)


async def resolve_text(
    db: AsyncSession, source_type: str, source_ref_id: str, http=None
) -> str:
    fn = _RESOLVERS.get(source_type)
    if fn is None:
        raise SourceNotFound(f"不支持的来源类型：{source_type}")
    return await fn(db, source_ref_id, http)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_kb_sources.py -v`
Expected: PASS（8 个用例）

- [ ] **Step 5: 写失败测试（ingest_text）**

在 `backend/tests/test_kb_ingest.py` 末尾追加：

```python
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
```

同时把该文件的 `_doc` 辅助函数改为支持 `title` 与可空 `filename`：

```python
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
```

- [ ] **Step 6: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_kb_ingest.py -v`
Expected: FAIL — `ImportError: cannot import name 'ingest_text' from 'app.kb.ingest'`

- [ ] **Step 7: 重构 ingest.py**

`backend/app/kb/ingest.py` 整个文件替换为：

```python
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
```

`embed_with_cache` 分批已在内部处理，原来的 `_EMBED_BATCH` 循环随之移到 `embedding_cache.py`。

- [ ] **Step 8: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_kb_ingest.py tests/test_kb_retrieval.py tests/test_kb_api.py tests/test_kb_flow.py -v`
Expected: 全 PASS（含原有的 `test_ingest_bad_type_marks_failed`——解析失败路径行为不变）

- [ ] **Step 9: 提交**

```bash
cd backend && uv run ruff check app tests
git add app/kb/sources.py app/kb/ingest.py tests/test_kb_sources.py tests/test_kb_ingest.py
git commit -m "feat(kb): 来源解析层 + ingest_text 重构，三条来源共用入库路径"
```

---

## Task 4: 入库服务与配额

**Files:**
- Create: `backend/app/kb/service.py`
- Test: `backend/tests/test_kb_dedup.py`
- Test: `backend/tests/test_kb_quota.py`

**Interfaces:**
- Consumes: Task 3 的 `describe()` / `SourceNotFound` / `SUPPORTED_ITEM_TYPES`
- Produces:
  - `async add_source_item(db, kb_id: uuid.UUID, source_type: str, source_ref_id: str, kb_source_id: uuid.UUID | None = None) -> tuple[Literal["added", "duplicate"], uuid.UUID | None]` — 返回 (结果, 新建文档 id)。`duplicate` 时第二项为 None
  - `async check_document_quota(db, kb_id: uuid.UUID, user: User) -> None` — 触顶抛 `QuotaExceeded`
  - `async check_source_quota(db, user: User) -> None` — 触顶抛 `QuotaExceeded`
  - `class QuotaExceeded(Exception)` — `.message: str` 存给用户看的文案

- [ ] **Step 1: 写失败测试（去重）**

创建 `backend/tests/test_kb_dedup.py`：

```python
import datetime as dt
import uuid

import pytest
from sqlalchemy import func, select

from app.auth.models import User
from app.core.security import hash_password
from app.kb.models import Kb, KbDocument
from app.kb.service import add_source_item
from app.kb.sources import SourceNotFound


async def _user_kb(db, name="库"):
    u = User(email=f"dd-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db.add(u)
    await db.flush()
    kb = Kb(owner_id=u.id, name=name)
    db.add(kb)
    await db.commit()
    return u, kb


async def _news_item(db, content="快讯正文"):
    from app.news.models import NewsItem, NewsSource

    src = NewsSource(name="s", type="sina_live", channel="news", config={})
    db.add(src)
    await db.flush()
    item = NewsItem(source_id=src.id, channel="news", external_id=f"n{uuid.uuid4().hex[:8]}",
                    content_hash=uuid.uuid4().hex, title="标题", content=content,
                    url=None, published_at=dt.datetime(2026, 7, 3, tzinfo=dt.UTC))
    db.add(item)
    await db.commit()
    return item


@pytest.mark.asyncio
async def test_add_creates_pending_document_with_meta(db_session):
    _, kb = await _user_kb(db_session)
    item = await _news_item(db_session)
    result, doc_id = await add_source_item(db_session, kb.id, "news_item", str(item.id))
    assert result == "added" and doc_id is not None
    doc = await db_session.get(KbDocument, doc_id)
    assert doc.status == "pending" and doc.title == "标题"
    assert doc.source_type == "news_item" and doc.source_ref_id == str(item.id)
    assert doc.published_at == item.published_at and doc.filename is None


@pytest.mark.asyncio
async def test_same_item_twice_in_one_kb_is_duplicate(db_session):
    _, kb = await _user_kb(db_session)
    item = await _news_item(db_session)
    assert (await add_source_item(db_session, kb.id, "news_item", str(item.id)))[0] == "added"
    result, doc_id = await add_source_item(db_session, kb.id, "news_item", str(item.id))
    assert result == "duplicate" and doc_id is None
    n = (await db_session.execute(
        select(func.count()).select_from(KbDocument).where(KbDocument.kb_id == kb.id)
    )).scalar_one()
    assert n == 1


@pytest.mark.asyncio
async def test_same_item_in_two_kbs_stored_separately(db_session):
    """不做全局内容去重：两个库各存一份文档。省的是 embedding 调用，不是 Postgres 存储。"""
    _, kb1 = await _user_kb(db_session, "库1")
    _, kb2 = await _user_kb(db_session, "库2")
    item = await _news_item(db_session)
    assert (await add_source_item(db_session, kb1.id, "news_item", str(item.id)))[0] == "added"
    assert (await add_source_item(db_session, kb2.id, "news_item", str(item.id)))[0] == "added"


@pytest.mark.asyncio
async def test_concurrent_insert_falls_back_to_duplicate(db_session, monkeypatch):
    """并发下「先查后插」有竞态窗口，靠唯一约束兜底 → IntegrityError 转 duplicate。"""
    _, kb = await _user_kb(db_session)
    item = await _news_item(db_session)
    # 先手工插一条绕过 add_source_item 的查重，模拟另一并发请求刚插入
    db_session.add(KbDocument(kb_id=kb.id, title="抢先", source_type="news_item",
                              source_ref_id=str(item.id), status="pending"))
    await db_session.commit()

    from app.kb import service

    async def _no_dup(db, kb_id, source_type, source_ref_id):
        return None                      # 假装查重没查到

    monkeypatch.setattr(service, "_find_existing", _no_dup)
    result, doc_id = await add_source_item(db_session, kb.id, "news_item", str(item.id))
    assert result == "duplicate" and doc_id is None


@pytest.mark.asyncio
async def test_missing_source_raises(db_session):
    _, kb = await _user_kb(db_session)
    with pytest.raises(SourceNotFound):
        await add_source_item(db_session, kb.id, "news_item", str(uuid.uuid4()))
    with pytest.raises(SourceNotFound):
        await add_source_item(db_session, kb.id, "xhs_note", str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_kb_source_id_is_recorded(db_session):
    """由整号订阅自动入库的文档带 kb_source_id，purge 时据此批量删除。"""
    from app.kb.models import KbSource

    _, kb = await _user_kb(db_session)
    src = KbSource(kb_id=kb.id, source_type="wechat_account",
                   source_ref_id=str(uuid.uuid4()), display_name="号")
    db_session.add(src)
    await db_session.flush()
    item = await _news_item(db_session)
    _, doc_id = await add_source_item(db_session, kb.id, "news_item", str(item.id),
                                      kb_source_id=src.id)
    doc = await db_session.get(KbDocument, doc_id)
    assert doc.kb_source_id == src.id
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_kb_dedup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.kb.service'`

- [ ] **Step 3: 实现 service.py**

创建 `backend/app/kb/service.py`：

```python
"""请求内的知识库业务逻辑：查重建行、配额检查。

与 ingest.py 的分工：这里跑在请求的 session 里（快、要事务一致）；ingest.py 跑在
后台任务里（慢、自己开 session）。混在一个文件里容易误用错的 session。
"""
import uuid
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.config import get_settings
from app.kb.models import Kb, KbDocument, KbSource
from app.kb.sources import describe


class QuotaExceeded(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


async def _find_existing(
    db: AsyncSession, kb_id: uuid.UUID, source_type: str, source_ref_id: str
) -> uuid.UUID | None:
    return await db.scalar(
        select(KbDocument.id).where(
            KbDocument.kb_id == kb_id,
            KbDocument.source_type == source_type,
            KbDocument.source_ref_id == source_ref_id,
        )
    )


async def add_source_item(
    db: AsyncSession,
    kb_id: uuid.UUID,
    source_type: str,
    source_ref_id: str,
    kb_source_id: uuid.UUID | None = None,
) -> tuple[Literal["added", "duplicate"], uuid.UUID | None]:
    """建一条 pending 文档行。正文抓取与切片由调用方丢后台。

    duplicate 不是错误——前端提示「已在库中」。source_type 不支持或源不存在时
    抛 SourceNotFound，由调用方转成 4xx / 批量结果里的 failed 项。
    """
    if await _find_existing(db, kb_id, source_type, source_ref_id) is not None:
        return "duplicate", None

    meta = await describe(db, source_type, source_ref_id)
    doc = KbDocument(
        kb_id=kb_id, title=meta.title[:512], filename=None,
        source_type=source_type, source_ref_id=source_ref_id,
        source_url=meta.source_url, published_at=meta.published_at,
        kb_source_id=kb_source_id, status="pending",
    )
    db.add(doc)
    try:
        await db.commit()
    except IntegrityError:
        # 并发窗口：另一请求刚插了同一条。唯一约束兜底，不依赖「先查后插」。
        await db.rollback()
        return "duplicate", None
    return "added", doc.id


async def check_document_quota(db: AsyncSession, kb_id: uuid.UUID, user: User) -> None:
    """单库文档数上限。上传文档也计入——上限管的是库的规模，不是来源。"""
    if user.role == "admin":
        return
    limit = get_settings().kb_max_documents_per_kb
    n = (await db.execute(
        select(func.count()).select_from(KbDocument).where(KbDocument.kb_id == kb_id)
    )).scalar_one()
    if n >= limit:
        raise QuotaExceeded(f"该知识库已达 {limit} 篇文档上限，请先清理或新建知识库")


async def check_source_quota(db: AsyncSession, user: User) -> None:
    """每用户订阅源总数上限（跨其所有知识库统计）。"""
    if user.role == "admin":
        return
    limit = get_settings().kb_max_sources_per_user
    n = (await db.execute(
        select(func.count()).select_from(KbSource)
        .join(Kb, Kb.id == KbSource.kb_id).where(Kb.owner_id == user.id)
    )).scalar_one()
    if n >= limit:
        raise QuotaExceeded(f"已达 {limit} 个订阅源上限，请先断开一些订阅")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_kb_dedup.py -v`
Expected: PASS（6 个用例）

- [ ] **Step 5: 写配额测试**

创建 `backend/tests/test_kb_quota.py`：

```python
import uuid

import pytest

from app.auth.models import User
from app.core import config
from app.core.security import hash_password
from app.kb.models import Kb, KbDocument, KbSource
from app.kb.service import (
    QuotaExceeded,
    check_document_quota,
    check_source_quota,
)


async def _user(db, role="user"):
    u = User(email=f"q-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"), role=role)
    db.add(u)
    await db.flush()
    return u


@pytest.fixture
def tiny_limits(monkeypatch):
    monkeypatch.setenv("KB_MAX_DOCUMENTS_PER_KB", "2")
    monkeypatch.setenv("KB_MAX_SOURCES_PER_USER", "1")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_document_quota_blocks_normal_user(db_session, tiny_limits):
    u = await _user(db_session)
    kb = Kb(owner_id=u.id, name="满库")
    db_session.add(kb)
    await db_session.flush()
    for i in range(2):
        db_session.add(KbDocument(kb_id=kb.id, title=f"d{i}", filename=f"d{i}.txt",
                                  source_type="upload", status="ready"))
    await db_session.commit()
    with pytest.raises(QuotaExceeded) as e:
        await check_document_quota(db_session, kb.id, u)
    assert "2 篇文档上限" in e.value.message


@pytest.mark.asyncio
async def test_document_quota_exempts_admin(db_session, tiny_limits):
    admin = await _user(db_session, role="admin")
    kb = Kb(owner_id=admin.id, name="管理员库")
    db_session.add(kb)
    await db_session.flush()
    for i in range(5):
        db_session.add(KbDocument(kb_id=kb.id, title=f"a{i}", filename=f"a{i}.txt",
                                  source_type="upload", status="ready"))
    await db_session.commit()
    await check_document_quota(db_session, kb.id, admin)   # 不抛


@pytest.mark.asyncio
async def test_document_quota_passes_under_limit(db_session, tiny_limits):
    u = await _user(db_session)
    kb = Kb(owner_id=u.id, name="空库")
    db_session.add(kb)
    await db_session.commit()
    await check_document_quota(db_session, kb.id, u)       # 不抛


@pytest.mark.asyncio
async def test_source_quota_counts_across_user_kbs(db_session, tiny_limits):
    u = await _user(db_session)
    kb = Kb(owner_id=u.id, name="订阅库")
    db_session.add(kb)
    await db_session.flush()
    db_session.add(KbSource(kb_id=kb.id, source_type="wechat_account",
                            source_ref_id=str(uuid.uuid4()), display_name="号1"))
    await db_session.commit()
    with pytest.raises(QuotaExceeded) as e:
        await check_source_quota(db_session, u)
    assert "1 个订阅源上限" in e.value.message


@pytest.mark.asyncio
async def test_source_quota_exempts_admin(db_session, tiny_limits):
    admin = await _user(db_session, role="admin")
    kb = Kb(owner_id=admin.id, name="k")
    db_session.add(kb)
    await db_session.flush()
    for i in range(3):
        db_session.add(KbSource(kb_id=kb.id, source_type="wechat_account",
                                source_ref_id=str(uuid.uuid4()), display_name=f"号{i}"))
    await db_session.commit()
    await check_source_quota(db_session, admin)            # 不抛
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_kb_quota.py -v`
Expected: PASS（5 个用例）

- [ ] **Step 7: 提交**

```bash
cd backend && uv run ruff check app tests
git add app/kb/service.py tests/test_kb_dedup.py tests/test_kb_quota.py
git commit -m "feat(kb): 入库服务 — 文档级幂等去重与配额检查"
```

## Task 5: 正文抓取限流器

整个设计最脆的一环。微信对文章页有风控，后台回填与用户点开文章的懒抓必须共用同一个限流器——否则回填会把前台阅读挤到超时。

**Files:**
- Create: `backend/app/kb/ratelimit.py`
- Modify: `backend/app/social/ingest.py`（`fetch_article_content` 走限流器）
- Test: `backend/tests/test_kb_ratelimit.py`

**Interfaces:**
- Produces:
  - `async with article_fetch_slot():` — 异步上下文管理器。串行化 + 保证两次进入间隔不小于 `kb_backfill_delay_seconds`
  - `reset_for_tests() -> None` — 清掉进程内状态，供测试隔离

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_kb_ratelimit.py`：

```python
import asyncio
import time

import pytest

from app.core import config
from app.kb.ratelimit import article_fetch_slot, reset_for_tests


@pytest.fixture
def fast_limiter(monkeypatch):
    monkeypatch.setenv("KB_BACKFILL_DELAY_SECONDS", "0.05")
    config.get_settings.cache_clear()
    reset_for_tests()
    yield
    config.get_settings.cache_clear()
    reset_for_tests()


@pytest.mark.asyncio
async def test_slot_serializes_concurrent_fetches(fast_limiter):
    """并发进入时必须串行，不能有两个同时持有 slot。"""
    active, peak = 0, 0

    async def worker():
        nonlocal active, peak
        async with article_fetch_slot():
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(*(worker() for _ in range(5)))
    assert peak == 1


@pytest.mark.asyncio
async def test_slot_enforces_minimum_interval(fast_limiter):
    started = []

    async def worker():
        async with article_fetch_slot():
            started.append(time.monotonic())

    await asyncio.gather(*(worker() for _ in range(3)))
    started.sort()
    gaps = [b - a for a, b in zip(started, started[1:], strict=False)]
    assert all(g >= 0.04 for g in gaps), gaps    # 0.05 间隔留一点抖动余量


@pytest.mark.asyncio
async def test_slot_releases_on_exception(fast_limiter):
    """抓取抛异常也必须释放，否则一次失败会永久卡死整条链路。"""
    with pytest.raises(RuntimeError):
        async with article_fetch_slot():
            raise RuntimeError("boom")
    async with article_fetch_slot():         # 还能再进
        pass
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_kb_ratelimit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.kb.ratelimit'`

- [ ] **Step 3: 实现**

创建 `backend/app/kb/ratelimit.py`：

```python
"""公众号正文抓取的进程内限流器。

后台回填与用户点开文章的懒抓共用同一个 slot——否则回填会把前台阅读挤到超时。
单进程语义（信号量 + 单调时钟），多副本部署时每个进程各限一份；当前部署形态为
单进程，够用。
"""
import asyncio
import contextlib
import time

from app.core.config import get_settings

_lock: asyncio.Lock | None = None
_last_at: float = 0.0


def _get_lock() -> asyncio.Lock:
    # 懒建：模块导入时可能还没有 event loop
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def reset_for_tests() -> None:
    global _lock, _last_at
    _lock = None
    _last_at = 0.0


@contextlib.asynccontextmanager
async def article_fetch_slot():
    """串行化正文抓取，并保证两次抓取间隔不小于 kb_backfill_delay_seconds。"""
    global _last_at
    delay = get_settings().kb_backfill_delay_seconds
    async with _get_lock():
        wait = _last_at + delay - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            yield
        finally:
            # 以「抓取结束」为计时起点，异常路径同样计时——失败往往正是被限流，
            # 不计时会让重试立刻再撞一次。
            _last_at = time.monotonic()
```

- [ ] **Step 4: 让懒抓走同一个 slot**

`backend/app/social/ingest.py` 的 `fetch_article_content` 改为：

```python
async def fetch_article_content(db: AsyncSession, article: WechatArticle, http) -> str:
    from app.kb.ratelimit import article_fetch_slot

    if article.content:
        return article.content
    # 与 KB 后台回填共用限流 slot：回填不得把前台阅读挤到超时
    async with article_fetch_slot():
        text = await fetch_article_text(http, article.url)
    article.content = text
    article.content_fetched_at = dt.datetime.now(dt.UTC)
    await db.commit()
    return text
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_kb_ratelimit.py tests/test_kb_sources.py tests/test_social_api.py -v`
Expected: 全 PASS

- [ ] **Step 6: 提交**

```bash
cd backend && uv run ruff check app tests
git add app/kb/ratelimit.py app/social/ingest.py tests/test_kb_ratelimit.py
git commit -m "feat(kb): 正文抓取限流器，前台懒抓与后台回填共用"
```

---

## Task 6: 后台入库任务与整号回填

**Files:**
- Create: `backend/app/kb/backfill.py`
- Test: `backend/tests/test_kb_backfill.py`

**Interfaces:**
- Consumes: Task 3 的 `resolve_text()`、Task 4 的 `add_source_item()`、Task 5 的 `article_fetch_slot()`
- Produces:
  - `async ingest_source_document(document_id: uuid.UUID, source_type: str, source_ref_id: str) -> None` — 单篇后台任务：resolve 正文 → `ingest_text`
  - `async backfill_source(kb_source_id: uuid.UUID) -> int` — 整号回填，返回新增文档数
  - `async ingest_new_articles_for_account(account_id: uuid.UUID, article_ids: list[uuid.UUID]) -> int` — poll 增量钩子，返回新增文档数

**关于「连续失败即中止」**：spec 第 186 行写「凭证池为空时整批暂停」，但正文抓取不走凭证池（见开头的偏差说明）。这里以连续失败计数实现同一意图。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_kb_backfill.py`：

```python
import datetime as dt
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.auth.models import User
from app.core import config
from app.core.security import hash_password
from app.kb.models import Kb, KbDocument, KbSource


@pytest.fixture
def fast_limiter(monkeypatch):
    monkeypatch.setenv("KB_BACKFILL_DELAY_SECONDS", "0")
    config.get_settings.cache_clear()
    from app.kb.ratelimit import reset_for_tests
    reset_for_tests()
    yield
    config.get_settings.cache_clear()
    reset_for_tests()


async def _kb(db):
    u = User(email=f"bf-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db.add(u)
    await db.flush()
    kb = Kb(owner_id=u.id, name="回填库")
    db.add(kb)
    await db.commit()
    return kb


async def _account_with_articles(db, n, content="正文内容"):
    from app.social.ingest import get_or_create_account
    from app.social.models import WechatArticle

    acc = await get_or_create_account(db, f"F{uuid.uuid4().hex[:8]}", "财经号")
    arts = []
    for i in range(n):
        a = WechatArticle(
            account_id=acc.id, external_id=f"a{uuid.uuid4().hex[:8]}", title=f"文章{i}",
            digest="", cover_url=None, url=f"https://mp.weixin.qq.com/s/{uuid.uuid4().hex[:6]}",
            content=content, published_at=dt.datetime(2026, 7, i + 1, tzinfo=dt.UTC),
        )
        db.add(a)
        arts.append(a)
    await db.commit()
    return acc, arts


@pytest.mark.asyncio
async def test_ingest_source_document_resolves_and_readies(db_session, fast_limiter):
    from app.kb.backfill import ingest_source_document
    from app.kb.service import add_source_item

    kb = await _kb(db_session)
    _, arts = await _account_with_articles(db_session, 1, content="茅台" * 500)
    _, doc_id = await add_source_item(db_session, kb.id, "wechat_article", str(arts[0].id))
    await ingest_source_document(doc_id, "wechat_article", str(arts[0].id))

    doc = await db_session.get(KbDocument, doc_id)
    await db_session.refresh(doc)
    assert doc.status == "ready" and doc.chunk_count >= 1 and doc.text


@pytest.mark.asyncio
async def test_ingest_source_document_marks_failed_on_fetch_error(db_session, fast_limiter,
                                                                 monkeypatch):
    """抓取失败 → 该篇标 failed，错误可见，不影响别的文档。"""
    from app.kb.backfill import ingest_source_document
    from app.kb.service import add_source_item

    kb = await _kb(db_session)
    _, arts = await _account_with_articles(db_session, 1, content=None)
    _, doc_id = await add_source_item(db_session, kb.id, "wechat_article", str(arts[0].id))
    # content 为空且 backfill 内部建的 http client 会真发请求 → mock 掉使其失败
    from app.kb import backfill

    def _boom():
        return httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(503, text="rate limited")))

    monkeypatch.setattr(backfill, "new_mp_client", _boom)
    await ingest_source_document(doc_id, "wechat_article", str(arts[0].id))

    doc = await db_session.get(KbDocument, doc_id)
    await db_session.refresh(doc)
    assert doc.status == "failed" and doc.error


@pytest.mark.asyncio
async def test_backfill_source_ingests_existing_articles(db_session, fast_limiter):
    from app.kb.backfill import backfill_source

    kb = await _kb(db_session)
    acc, arts = await _account_with_articles(db_session, 3)
    src = KbSource(kb_id=kb.id, source_type="wechat_account",
                   source_ref_id=str(acc.id), display_name="财经号")
    db_session.add(src)
    await db_session.commit()

    added = await backfill_source(src.id)
    assert added == 3
    n = (await db_session.execute(
        select(func.count()).select_from(KbDocument)
        .where(KbDocument.kb_id == kb.id, KbDocument.status == "ready")
    )).scalar_one()
    assert n == 3
    await db_session.refresh(src)
    assert src.status == "ready" and src.last_synced_at is not None


@pytest.mark.asyncio
async def test_backfill_is_idempotent(db_session, fast_limiter):
    """重跑安全：进程重启丢了任务，下次同步补上，不产生重复。"""
    from app.kb.backfill import backfill_source

    kb = await _kb(db_session)
    acc, _ = await _account_with_articles(db_session, 2)
    src = KbSource(kb_id=kb.id, source_type="wechat_account",
                   source_ref_id=str(acc.id), display_name="号")
    db_session.add(src)
    await db_session.commit()

    assert await backfill_source(src.id) == 2
    assert await backfill_source(src.id) == 0        # 第二次全是 duplicate
    n = (await db_session.execute(
        select(func.count()).select_from(KbDocument).where(KbDocument.kb_id == kb.id)
    )).scalar_one()
    assert n == 2


@pytest.mark.asyncio
async def test_backfill_aborts_after_consecutive_failures(db_session, fast_limiter, monkeypatch):
    """连续失败 3 篇即中止本批，别把几十篇全标脏。"""
    monkeypatch.setenv("KB_BACKFILL_MAX_FAILURES", "3")
    config.get_settings.cache_clear()

    from app.kb import backfill

    kb = await _kb(db_session)
    acc, _ = await _account_with_articles(db_session, 10, content=None)
    src = KbSource(kb_id=kb.id, source_type="wechat_account",
                   source_ref_id=str(acc.id), display_name="号")
    db_session.add(src)
    await db_session.commit()

    calls = []

    async def _always_fail(db, source_type, source_ref_id, http=None):
        calls.append(source_ref_id)
        raise RuntimeError("被限流")

    monkeypatch.setattr(backfill, "resolve_text", _always_fail)
    added = await backfill.backfill_source(src.id)
    assert added == 0
    assert len(calls) == 3            # 第 3 次连续失败后中止，不再碰剩下 7 篇
    await db_session.refresh(src)
    assert src.status == "failed" and src.error


@pytest.mark.asyncio
async def test_backfill_marks_limited_on_quota(db_session, fast_limiter, monkeypatch):
    """触顶时置 status=limited 停止入库，面板可见，不静默丢弃。"""
    monkeypatch.setenv("KB_MAX_DOCUMENTS_PER_KB", "1")
    config.get_settings.cache_clear()

    from app.kb.backfill import backfill_source

    kb = await _kb(db_session)
    acc, _ = await _account_with_articles(db_session, 3)
    src = KbSource(kb_id=kb.id, source_type="wechat_account",
                   source_ref_id=str(acc.id), display_name="号")
    db_session.add(src)
    await db_session.commit()

    added = await backfill_source(src.id)
    assert added == 1                 # 第 2 篇时触顶
    await db_session.refresh(src)
    assert src.status == "limited"


@pytest.mark.asyncio
async def test_poll_hook_ingests_new_articles(db_session, fast_limiter):
    """增量：poll 到新文章后，订阅了该号的每个 KbSource 各入一份。"""
    from app.kb.backfill import ingest_new_articles_for_account

    kb1 = await _kb(db_session)
    kb2 = await _kb(db_session)
    acc, arts = await _account_with_articles(db_session, 2)
    for kb in (kb1, kb2):
        db_session.add(KbSource(kb_id=kb.id, source_type="wechat_account",
                                source_ref_id=str(acc.id), display_name="号"))
    await db_session.commit()

    added = await ingest_new_articles_for_account(acc.id, [a.id for a in arts])
    assert added == 4                 # 2 篇 × 2 个库
    for kb in (kb1, kb2):
        n = (await db_session.execute(
            select(func.count()).select_from(KbDocument).where(KbDocument.kb_id == kb.id)
        )).scalar_one()
        assert n == 2


@pytest.mark.asyncio
async def test_poll_hook_skips_disabled_sources(db_session, fast_limiter):
    from app.kb.backfill import ingest_new_articles_for_account

    kb = await _kb(db_session)
    acc, arts = await _account_with_articles(db_session, 1)
    db_session.add(KbSource(kb_id=kb.id, source_type="wechat_account",
                            source_ref_id=str(acc.id), display_name="号", enabled=False))
    await db_session.commit()
    assert await ingest_new_articles_for_account(acc.id, [arts[0].id]) == 0


@pytest.mark.asyncio
async def test_poll_hook_noop_without_subscribers(db_session, fast_limiter):
    from app.kb.backfill import ingest_new_articles_for_account

    acc, arts = await _account_with_articles(db_session, 1)
    assert await ingest_new_articles_for_account(acc.id, [arts[0].id]) == 0
```

注意 `test_backfill_aborts_after_consecutive_failures` 里那个 `backfill_source_wrapper` 只是为了让 monkeypatch 生效顺序清晰（先 patch 再取函数），实现时直接 `await backfill.backfill_source(src.id)` 亦可，两者等价。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_kb_backfill.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.kb.backfill'`

- [ ] **Step 3: 实现**

创建 `backend/app/kb/backfill.py`：

```python
"""后台入库任务：单篇 resolve+切片，整号回填，poll 增量钩子。

三者都自己开 session（跑在 BackgroundTasks / scheduler 里，没有请求 session），
且都幂等——重跑只会得到 duplicate，不产生重复文档。
"""
import logging
import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.kb.ingest import ingest_text
from app.kb.models import Kb, KbDocument, KbSource
from app.kb.ratelimit import article_fetch_slot
from app.kb.service import QuotaExceeded, add_source_item, check_document_quota
from app.kb.sources import resolve_text
from app.social.wechat.client import new_mp_client

_log = logging.getLogger(__name__)
# 需要走网络抓正文的来源。news_item 直接读库，不必占限流 slot。
_NEEDS_FETCH = {"wechat_article"}


async def _resolve(source_type: str, source_ref_id: str) -> str:
    """取正文。需要回源的来源走限流 slot，并与前台懒抓共用。"""
    sm = get_sessionmaker()
    if source_type not in _NEEDS_FETCH:
        async with sm() as db:
            return await resolve_text(db, source_type, source_ref_id)
    async with new_mp_client() as http, sm() as db:
        async with article_fetch_slot():
            return await resolve_text(db, source_type, source_ref_id, http=http)


async def ingest_source_document(
    document_id: uuid.UUID, source_type: str, source_ref_id: str
) -> None:
    """单篇后台任务：取正文 → 切片入库。失败落在 doc.status='failed'，绝不抛。"""
    try:
        text = await _resolve(source_type, source_ref_id)
    except Exception as e:  # noqa: BLE001 — 后台任务：失败写库不抛
        _log.exception("resolve failed for document %s", document_id)
        sm = get_sessionmaker()
        async with sm() as db:
            doc = await db.get(KbDocument, document_id)
            if doc is not None:
                doc.status = "failed"
                doc.error = f"正文获取失败：{e}"[:500]
                await db.commit()
        return
    await ingest_text(document_id, text)


async def _owner_of(db, kb_id: uuid.UUID):
    from app.auth.models import User

    return await db.scalar(select(User).join(Kb, Kb.owner_id == User.id).where(Kb.id == kb_id))


async def _ingest_one(kb_id: uuid.UUID, source_type: str, source_ref_id: str,
                      kb_source_id: uuid.UUID | None) -> str:
    """建行 + 入库，返回 'added' / 'duplicate'。配额与解析错误由调用方处理。"""
    sm = get_sessionmaker()
    async with sm() as db:
        owner = await _owner_of(db, kb_id)
        if owner is None:
            return "duplicate"        # 库已被删，静默跳过
        await check_document_quota(db, kb_id, owner)
        result, doc_id = await add_source_item(db, kb_id, source_type, source_ref_id,
                                              kb_source_id=kb_source_id)
    if result == "duplicate":
        return "duplicate"
    await ingest_source_document(doc_id, source_type, source_ref_id)
    return "added"


async def backfill_source(kb_source_id: uuid.UUID) -> int:
    """把该号在 wechat_articles 里已有的文章逐篇入库。不回溯翻页拉历史。

    重跑安全（查重幂等）。连续失败达 kb_backfill_max_failures 篇即中止本批——
    正文抓取一旦被风控挡住，继续跑只会把几十篇全标脏。
    """
    s = get_settings()
    sm = get_sessionmaker()
    async with sm() as db:
        src = await db.get(KbSource, kb_source_id)
        if src is None or not src.enabled:
            return 0
        src.status = "syncing"
        src.error = None
        await db.commit()
        kb_id, ref, source_type = src.kb_id, src.source_ref_id, src.source_type

    article_ids = await _pending_article_ids(source_type, ref, s.kb_backfill_batch_limit)

    added, consecutive_failures, final_status, err = 0, 0, "ready", None
    for aid in article_ids:
        try:
            if await _ingest_one(kb_id, "wechat_article", str(aid), kb_source_id) == "added":
                added += 1
            consecutive_failures = 0
        except QuotaExceeded as e:
            final_status, err = "limited", e.message
            break
        except Exception as e:  # noqa: BLE001 — 单篇失败隔离
            _log.warning("backfill failed for article %s: %s", aid, e)
            consecutive_failures += 1
            if consecutive_failures >= s.kb_backfill_max_failures:
                final_status = "failed"
                err = f"连续 {consecutive_failures} 篇获取失败，已中止本次同步：{e}"
                break

    import datetime as dt

    async with sm() as db:
        src = await db.get(KbSource, kb_source_id)
        if src is not None:
            src.status = final_status
            src.error = (err or None) and err[:500]
            src.last_synced_at = dt.datetime.now(dt.UTC)
            await db.commit()
    return added


async def _pending_article_ids(source_type: str, source_ref_id: str, limit: int) -> list[uuid.UUID]:
    """该号已有文章里、尚未入过库的，按发布时间倒序取前 limit 篇。"""
    if source_type != "wechat_account":
        return []
    from app.social.models import WechatArticle

    sm = get_sessionmaker()
    async with sm() as db:
        rows = (await db.execute(
            select(WechatArticle.id)
            .where(WechatArticle.account_id == uuid.UUID(source_ref_id))
            .order_by(WechatArticle.published_at.desc()).limit(limit)
        )).scalars().all()
    return list(rows)


async def ingest_new_articles_for_account(
    account_id: uuid.UUID, article_ids: list[uuid.UUID]
) -> int:
    """poll 钩子：本轮该号新增的文章，为订阅了它的每个 KbSource 各入一份。"""
    if not article_ids:
        return 0
    sm = get_sessionmaker()
    async with sm() as db:
        sources = (await db.execute(
            select(KbSource).where(
                KbSource.source_type == "wechat_account",
                KbSource.source_ref_id == str(account_id),
                KbSource.enabled.is_(True),
            )
        )).scalars().all()
        targets = [(src.kb_id, src.id) for src in sources]
    if not targets:
        return 0

    added = 0
    for kb_id, src_id in targets:
        for aid in article_ids:
            try:
                if await _ingest_one(kb_id, "wechat_article", str(aid), src_id) == "added":
                    added += 1
            except QuotaExceeded as e:
                async with sm() as db:
                    src = await db.get(KbSource, src_id)
                    if src is not None:
                        src.status = "limited"
                        src.error = e.message[:500]
                        await db.commit()
                break
            except Exception:  # noqa: BLE001 — 单篇失败隔离，不拖累同批
                _log.exception("kb poll ingest failed: kb=%s article=%s", kb_id, aid)
    return added
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_kb_backfill.py -v`
Expected: PASS（9 个用例）

- [ ] **Step 5: 提交**

```bash
cd backend && uv run ruff check app tests
git add app/kb/backfill.py tests/test_kb_backfill.py
git commit -m "feat(kb): 后台入库任务 — 单篇切片、整号回填、连续失败中止"
```

---

## Task 7: poll 增量接线

`ingest_account()` 现在只返回新增数量，钩子需要知道**哪些**文章是新增的。改为返回 id 列表，调用方用 `len()` 保持原计数语义。

**Files:**
- Modify: `backend/app/social/ingest.py:23-43`
- Modify: `backend/app/social/job.py:37`
- Modify: `backend/app/social/router.py:187`
- Test: `backend/tests/test_social_job.py`（扩展）

**Interfaces:**
- Consumes: Task 6 的 `ingest_new_articles_for_account()`
- Produces: `async ingest_account(db, account, cred, http, count=20) -> list[uuid.UUID]` — 返回本轮新增文章的 id 列表（原为 `int`）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_social_job.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_ingest_account_returns_new_article_ids(db_session):
    """返回 id 列表而非计数：KB 增量钩子需要知道哪些是新增的。"""
    from app.social.ingest import get_or_create_account, ingest_account
    from app.social.wechat.client import ActiveCred

    acc = await get_or_create_account(db_session, f"F{uuid.uuid4().hex[:6]}", "号")
    aids = [f"r{uuid.uuid4().hex[:6]}", f"r{uuid.uuid4().hex[:6]}"]
    http = httpx.AsyncClient(transport=httpx.MockTransport(_appmsg_handler(aids)))

    ids = await ingest_account(db_session, acc, ActiveCred(id=uuid.uuid4(), token="t", cookies="c"), http)
    assert isinstance(ids, list) and len(ids) == 2
    rows = (await db_session.execute(
        select(WechatArticle.id).where(WechatArticle.account_id == acc.id)
    )).scalars().all()
    assert set(ids) == set(rows)

    # 第二次同样的 aid → 无新增
    http2 = httpx.AsyncClient(transport=httpx.MockTransport(_appmsg_handler(aids)))
    assert await ingest_account(db_session, acc, ActiveCred(id=uuid.uuid4(), token="t", cookies="c"), http2) == []


@pytest.mark.asyncio
async def test_poll_calls_kb_hook_with_new_ids(db_session, monkeypatch):
    """poll 拿到新增 id 后调 KB 钩子；计数语义不变（仍返回新增文章数）。"""
    from app.core.security import hash_password
    from app.social import job
    from app.social.ingest import get_or_create_account
    from app.social.models import WechatSubscription
    from app.social.wechat.client import ActiveCred

    u = User(email=f"hook-{uuid.uuid4().hex[:6]}@t.dev", password_hash=hash_password("x"))
    db_session.add(u)
    await db_session.flush()
    acc = await get_or_create_account(db_session, f"F{uuid.uuid4().hex[:6]}", "号")
    db_session.add(WechatSubscription(user_id=u.id, account_id=acc.id, enabled=True))
    await db_session.commit()

    aids = [f"h{uuid.uuid4().hex[:6]}"]
    seen = []

    async def fake_hook(account_id, article_ids):
        seen.append((account_id, list(article_ids)))
        return 0

    async def fake_pick(db):
        return ActiveCred(id=uuid.uuid4(), token="t", cookies="c")

    monkeypatch.setattr(job, "pick_credential", fake_pick)
    monkeypatch.setattr(job, "new_mp_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_appmsg_handler(aids))))
    monkeypatch.setattr(job, "ingest_new_articles_for_account", fake_hook)

    added = await job.poll_all_subscriptions()
    assert added == 1                       # 计数语义保持不变
    assert len(seen) == 1 and seen[0][0] == acc.id and len(seen[0][1]) == 1


@pytest.mark.asyncio
async def test_poll_survives_kb_hook_failure(db_session, monkeypatch):
    """KB 入库出问题不该让社媒 poll 整轮失败——两者是独立关注点。"""
    from app.core.security import hash_password
    from app.social import job
    from app.social.ingest import get_or_create_account
    from app.social.models import WechatSubscription
    from app.social.wechat.client import ActiveCred

    u = User(email=f"hookf-{uuid.uuid4().hex[:6]}@t.dev", password_hash=hash_password("x"))
    db_session.add(u)
    await db_session.flush()
    acc = await get_or_create_account(db_session, f"F{uuid.uuid4().hex[:6]}", "号")
    db_session.add(WechatSubscription(user_id=u.id, account_id=acc.id, enabled=True))
    await db_session.commit()

    async def boom(account_id, article_ids):
        raise RuntimeError("kb 挂了")

    async def fake_pick(db):
        return ActiveCred(id=uuid.uuid4(), token="t", cookies="c")

    monkeypatch.setattr(job, "pick_credential", fake_pick)
    monkeypatch.setattr(job, "new_mp_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(_appmsg_handler([f"k{uuid.uuid4().hex[:6]}"]))))
    monkeypatch.setattr(job, "ingest_new_articles_for_account", boom)

    assert await job.poll_all_subscriptions() == 1   # 不抛，计数照常
```

该文件顶部 import 需补 `from app.auth.models import User`（现有已有，第 8 行）与 `select`（已有）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_social_job.py -v`
Expected: FAIL — `test_ingest_account_returns_new_article_ids` 报 `assert isinstance(ids, list)` 失败（当前返回 int）

- [ ] **Step 3: 改 ingest_account 返回值**

`backend/app/social/ingest.py` 的 `ingest_account` 整体替换：

```python
async def ingest_account(
    db: AsyncSession, account: WechatAccount, cred: ActiveCred, http, count: int = 20
) -> list[uuid.UUID]:
    """增量抓取该号文章，返回本轮新增文章的 id 列表。

    返回 id 而非计数：KB 整号订阅的增量钩子需要知道具体是哪几篇。调用方要计数
    直接 len()。
    """
    from app.core.config import get_settings

    n = count or get_settings().social_fetch_count
    raws = await appmsg_publish(http, cred, account.fakeid, begin=0, count=n)
    new_ids: list[uuid.UUID] = []
    for raw in raws:
        exists = await db.scalar(
            select(WechatArticle.id).where(
                WechatArticle.account_id == account.id, WechatArticle.external_id == raw.external_id
            )
        )
        if exists is not None:
            continue
        art = WechatArticle(
            account_id=account.id, external_id=raw.external_id, title=raw.title,
            digest=raw.digest, cover_url=raw.cover_url, url=raw.url, published_at=raw.published_at,
        )
        db.add(art)
        await db.flush()          # 拿到自动生成的 id
        new_ids.append(art.id)
    await db.commit()
    return new_ids
```

文件顶部 import 补 `uuid`：

```python
import datetime as dt
import uuid
```

- [ ] **Step 4: 改 job.py 接线**

`backend/app/social/job.py`：import 段加一行

```python
from app.kb.backfill import ingest_new_articles_for_account
```

`poll_all_subscriptions` 的循环体替换为：

```python
    total = 0
    async with new_mp_client() as http:
        for account in accounts:
            try:
                async with get_sessionmaker()() as db:
                    acc = await db.get(WechatAccount, account.id)
                    new_ids = await ingest_account(db, acc, cred, http)
                total += len(new_ids)
                if new_ids:
                    # KB 整号订阅的增量入库。失败不拖累社媒 poll——两者独立关注点。
                    try:
                        await ingest_new_articles_for_account(account.id, new_ids)
                    except Exception:  # noqa: BLE001
                        _log.exception("kb incremental ingest failed for account %s", account.id)
            except SessionExpiredError:
                async with get_sessionmaker()() as db:
                    await mark_expired(db, cred.id)
                _log.warning("social poll: 凭证失效，本轮中止")
                break
            except TransientMpError:
                _log.warning("social poll: 临时错误，跳过 %s", account.id)
            except Exception:  # noqa: BLE001 — 单号失败隔离
                _log.exception("social poll failed for account %s", account.id)
    return total
```

- [ ] **Step 5: 改 router.py 适配**

`backend/app/social/router.py` 的 `refresh` 端点（第 187 行附近）：

```python
    try:
        async with new_mp_client() as http:
            new_ids = await ingest_account(db, acc, cred, http)
    except SessionExpiredError:
        await mark_expired(db, cred.id)
        raise HTTPException(409, "凭证已失效，请重新扫码登录")
    except TransientMpError:
        raise HTTPException(503, "微信接口暂时不可用（限流），请稍后重试")
    if new_ids:
        from app.kb.backfill import ingest_new_articles_for_account

        background.add_task(ingest_new_articles_for_account, acc.id, new_ids)
    return {"added": len(new_ids)}
```

该端点的签名要加 `BackgroundTasks`（手动刷新出的新文章也该进订阅了该号的知识库，但不能让用户等）：

```python
@router.post("/wechat/refresh")
async def refresh(
    account_id: uuid.UUID, background: BackgroundTasks,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
```

顶部 import 补 `BackgroundTasks`：

```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_social_job.py tests/test_social_api.py tests/test_kb_backfill.py -v`
Expected: 全 PASS

- [ ] **Step 7: 提交**

```bash
cd backend && uv run ruff check app tests
git add app/social/ingest.py app/social/job.py app/social/router.py tests/test_social_job.py
git commit -m "feat(kb): poll 增量接线 — ingest_account 返回新增 id 并触发 KB 入库"
```

## Task 8: API 端点

**Files:**
- Modify: `backend/app/kb/schemas.py`
- Modify: `backend/app/kb/router.py`
- Test: `backend/tests/test_kb_items_api.py`
- Test: `backend/tests/test_kb_sources_api.py`

**Interfaces:**
- Consumes: Task 3 `SUPPORTED_ITEM_TYPES` / `SourceNotFound`；Task 4 `add_source_item` / `check_document_quota` / `check_source_quota` / `QuotaExceeded`；Task 6 `ingest_source_document` / `backfill_source`
- Produces（schemas）：
  - `ItemIn`: `source_type: str`、`source_ref_id: str`
  - `ItemsIn`: `items: list[ItemIn]`
  - `ItemsResult`: `added: int`、`duplicate: int`、`failed: list[dict]`
  - `SourceIn`: `source_type: str`、`source_ref_id: str`、`display_name: str`
  - `SourceOut`: `id`、`source_type`、`source_ref_id`、`display_name`、`status`、`enabled`、`error`、`last_synced_at: str | None`
  - `DocumentOut`: `id`、`title`、`filename`、`status`、`chunk_count`、`error`、`source_type`、`source_url`、`published_at: str | None`
  - `DocumentDetailOut`: `DocumentOut` 全部字段 + `text: str | None`
- Produces（端点）：
  - `GET /api/kb/{kb_id}/documents?limit=&offset=` → `list[DocumentOut]`，按 `published_at` 倒序（NULL 末尾）、`created_at` 次序
  - `GET /api/kb/{kb_id}/documents/{doc_id}` → `DocumentDetailOut`
  - `DELETE /api/kb/{kb_id}/documents/{doc_id}` → `{"deleted": true}`
  - `POST /api/kb/{kb_id}/items` → `ItemsResult`
  - `POST /api/kb/{kb_id}/sources` → `SourceOut`
  - `GET /api/kb/{kb_id}/sources` → `list[SourceOut]`
  - `DELETE /api/kb/{kb_id}/sources/{source_id}?purge=false` → `{"deleted": true, "purged": n}`

- [ ] **Step 1: 写失败测试（items）**

创建 `backend/tests/test_kb_items_api.py`：

```python
import asyncio
import datetime as dt
import uuid

import pytest

from tests.conftest import _auth


async def _news_item(db, title="央行降准", content="快讯正文内容够长一点。"):
    from app.news.models import NewsItem, NewsSource

    src = NewsSource(name="s", type="sina_live", channel="news", config={})
    db.add(src)
    await db.flush()
    item = NewsItem(source_id=src.id, channel="news", external_id=f"n{uuid.uuid4().hex[:8]}",
                    content_hash=uuid.uuid4().hex, title=title, content=content,
                    url="https://finance.sina.com.cn/x",
                    published_at=dt.datetime(2026, 7, 5, tzinfo=dt.UTC))
    db.add(item)
    await db.commit()
    return item


async def _wait_ready(client, kb_id, headers, expect=1):
    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=headers)).json()
        if len([d for d in docs if d["status"] in ("ready", "failed")]) >= expect:
            return docs
        await asyncio.sleep(0.1)
    return docs


@pytest.mark.asyncio
async def test_add_item_then_document_becomes_ready(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "快讯库"}, headers=h)).json()["id"]
    item = await _news_item(db_session)

    r = await client.post(f"/api/kb/{kb_id}/items", headers=h, json={
        "items": [{"source_type": "news_item", "source_ref_id": str(item.id)}]})
    assert r.status_code == 200
    assert r.json() == {"added": 1, "duplicate": 0, "failed": []}

    docs = await _wait_ready(client, kb_id, h)
    assert docs[0]["status"] == "ready"
    assert docs[0]["title"] == "央行降准"
    assert docs[0]["source_type"] == "news_item"
    assert docs[0]["published_at"].startswith("2026-07-05")


@pytest.mark.asyncio
async def test_add_same_item_twice_reports_duplicate(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "去重库"}, headers=h)).json()["id"]
    item = await _news_item(db_session)
    body = {"items": [{"source_type": "news_item", "source_ref_id": str(item.id)}]}
    assert (await client.post(f"/api/kb/{kb_id}/items", headers=h, json=body)).json()["added"] == 1
    r2 = (await client.post(f"/api/kb/{kb_id}/items", headers=h, json=body)).json()
    assert r2 == {"added": 0, "duplicate": 1, "failed": []}


@pytest.mark.asyncio
async def test_batch_partial_failure_does_not_block_others(client, db_session, registered_user):
    """单条失败不影响同批其余条目。"""
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "混合库"}, headers=h)).json()["id"]
    ok = await _news_item(db_session)
    missing = str(uuid.uuid4())
    bad_type_ref = str(uuid.uuid4())

    r = (await client.post(f"/api/kb/{kb_id}/items", headers=h, json={"items": [
        {"source_type": "news_item", "source_ref_id": str(ok.id)},
        {"source_type": "news_item", "source_ref_id": missing},
        {"source_type": "xhs_note", "source_ref_id": bad_type_ref},
    ]})).json()
    assert r["added"] == 1 and r["duplicate"] == 0
    assert {f["source_ref_id"] for f in r["failed"]} == {missing, bad_type_ref}
    assert all(f["error"] for f in r["failed"])


@pytest.mark.asyncio
async def test_items_rejects_empty_and_oversized_batch(client, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "边界库"}, headers=h)).json()["id"]
    assert (await client.post(f"/api/kb/{kb_id}/items", headers=h,
                              json={"items": []})).status_code == 422
    too_many = [{"source_type": "news_item", "source_ref_id": str(uuid.uuid4())} for _ in range(51)]
    assert (await client.post(f"/api/kb/{kb_id}/items", headers=h,
                              json={"items": too_many})).status_code == 422


@pytest.mark.asyncio
async def test_items_on_foreign_kb_is_404(client, db_session, registered_user):
    h = _auth(registered_user)
    item = await _news_item(db_session)
    r = await client.post("/api/kb/00000000-0000-0000-0000-000000000000/items", headers=h,
                          json={"items": [{"source_type": "news_item",
                                           "source_ref_id": str(item.id)}]})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_document_detail_returns_text_snapshot(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "详情库"}, headers=h)).json()["id"]
    item = await _news_item(db_session, content="这是入库时的文本快照，详情页展示的就是它。")
    await client.post(f"/api/kb/{kb_id}/items", headers=h, json={
        "items": [{"source_type": "news_item", "source_ref_id": str(item.id)}]})
    docs = await _wait_ready(client, kb_id, h)
    doc_id = docs[0]["id"]

    d = (await client.get(f"/api/kb/{kb_id}/documents/{doc_id}", headers=h)).json()
    assert d["text"].startswith("这是入库时的文本快照")
    assert d["source_url"] == item.url
    # 他人库 / 不存在的文档 → 404
    assert (await client.get(f"/api/kb/{kb_id}/documents/{uuid.uuid4()}",
                             headers=h)).status_code == 404


@pytest.mark.asyncio
async def test_delete_document(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "删除库"}, headers=h)).json()["id"]
    item = await _news_item(db_session)
    await client.post(f"/api/kb/{kb_id}/items", headers=h, json={
        "items": [{"source_type": "news_item", "source_ref_id": str(item.id)}]})
    docs = await _wait_ready(client, kb_id, h)
    doc_id = docs[0]["id"]

    assert (await client.delete(f"/api/kb/{kb_id}/documents/{doc_id}",
                                headers=h)).status_code == 200
    assert (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json() == []
    # 删过之后可以重新加入（唯一约束随文档一起消失）
    assert (await client.post(f"/api/kb/{kb_id}/items", headers=h, json={
        "items": [{"source_type": "news_item", "source_ref_id": str(item.id)}]})
    ).json()["added"] == 1


@pytest.mark.asyncio
async def test_documents_pagination_and_ordering(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "分页库"}, headers=h)).json()["id"]
    items = [await _news_item(db_session, title=f"快讯{i}") for i in range(3)]
    await client.post(f"/api/kb/{kb_id}/items", headers=h, json={"items": [
        {"source_type": "news_item", "source_ref_id": str(i.id)} for i in items]})
    await _wait_ready(client, kb_id, h, expect=3)

    page = (await client.get(f"/api/kb/{kb_id}/documents?limit=2&offset=0", headers=h)).json()
    assert len(page) == 2
    rest = (await client.get(f"/api/kb/{kb_id}/documents?limit=2&offset=2", headers=h)).json()
    assert len(rest) == 1
    assert {d["id"] for d in page}.isdisjoint({d["id"] for d in rest})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_kb_items_api.py -v`
Expected: FAIL — `POST /api/kb/{kb_id}/items` 返回 405（路由不存在）

- [ ] **Step 3: 扩展 schemas.py**

`backend/app/kb/schemas.py` 整个文件替换为：

```python
from pydantic import BaseModel, Field


class KbCreate(BaseModel):
    name: str


class KbOut(BaseModel):
    id: str
    name: str
    is_shared: bool
    doc_count: int


class ItemIn(BaseModel):
    source_type: str
    source_ref_id: str


class ItemsIn(BaseModel):
    # 批量上限 50：再多会让请求内的 describe 循环拖长，且前端一次也选不了那么多
    items: list[ItemIn] = Field(min_length=1, max_length=50)


class ItemsResult(BaseModel):
    added: int
    duplicate: int
    failed: list[dict]


class SourceIn(BaseModel):
    source_type: str
    source_ref_id: str
    display_name: str


class SourceOut(BaseModel):
    id: str
    source_type: str
    source_ref_id: str
    display_name: str
    status: str
    enabled: bool
    error: str | None
    last_synced_at: str | None


class DocumentOut(BaseModel):
    id: str
    title: str
    filename: str | None
    status: str
    chunk_count: int
    error: str | None
    source_type: str
    source_url: str | None
    published_at: str | None


class DocumentDetailOut(DocumentOut):
    text: str | None
```

- [ ] **Step 4: 实现端点**

`backend/app/kb/router.py`——顶部 import 替换为：

```python
import secrets
import uuid

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile,
)
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.config import get_settings
from app.core.db import get_db
from app.kb.backfill import backfill_source, ingest_source_document
from app.kb.ingest import ingest_document
from app.kb.models import Kb, KbDocument, KbSource, KbSubscription
from app.kb.schemas import (
    DocumentDetailOut, DocumentOut, ItemsIn, ItemsResult, KbCreate, KbOut,
    SourceIn, SourceOut,
)
from app.kb.service import (
    QuotaExceeded, add_source_item, check_document_quota, check_source_quota,
)
from app.kb.sources import SourceNotFound
```

在 `_owned_kb` 之后加两个辅助函数与序列化：

```python
async def _owned_document(db: AsyncSession, kb: Kb, doc_id: str) -> KbDocument:
    try:
        did = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(404, "文档不存在")
    doc = await db.get(KbDocument, did)
    if doc is None or doc.kb_id != kb.id:
        raise HTTPException(404, "文档不存在")
    return doc


def _doc_out(d: KbDocument) -> dict:
    return {
        "id": str(d.id), "title": d.title, "filename": d.filename, "status": d.status,
        "chunk_count": d.chunk_count, "error": d.error, "source_type": d.source_type,
        "source_url": d.source_url,
        "published_at": d.published_at.isoformat() if d.published_at else None,
    }


def _source_out(s: KbSource) -> dict:
    return {
        "id": str(s.id), "source_type": s.source_type, "source_ref_id": s.source_ref_id,
        "display_name": s.display_name, "status": s.status, "enabled": s.enabled,
        "error": s.error,
        "last_synced_at": s.last_synced_at.isoformat() if s.last_synced_at else None,
    }
```

`list_documents` 端点替换为（加分页与新字段）：

```python
@router.get("/{kb_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    kb_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    kb = await _owned_kb(db, user, kb_id)
    docs = (await db.execute(
        select(KbDocument).where(KbDocument.kb_id == kb.id)
        # 按原始发布时间倒序（上传文档无此值，NULL 排末尾），同刻用 created_at 兜底
        .order_by(KbDocument.published_at.desc().nullslast(), KbDocument.created_at.desc())
        .limit(limit).offset(offset)
    )).scalars().all()
    return [_doc_out(d) for d in docs]
```

在 `list_documents` 之后追加新端点：

```python
@router.get("/{kb_id}/documents/{doc_id}", response_model=DocumentDetailOut)
async def get_document(
    kb_id: str, doc_id: str,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    kb = await _owned_kb(db, user, kb_id)
    doc = await _owned_document(db, kb, doc_id)
    # 详情展示入库时的文本快照，不回源重抓：检索命中的就是这份文本，
    # 展示与检索必须一致，否则用户会看到「AI 引用的和我看到的不一样」。
    return {**_doc_out(doc), "text": doc.text}


@router.delete("/{kb_id}/documents/{doc_id}")
async def delete_document(
    kb_id: str, doc_id: str,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    kb = await _owned_kb(db, user, kb_id)
    doc = await _owned_document(db, kb, doc_id)
    await db.delete(doc)          # kb_chunks 靠 FK ondelete=CASCADE 连带删除
    await db.commit()
    return {"deleted": True}


@router.post("/{kb_id}/items", response_model=ItemsResult)
async def add_items(
    kb_id: str, body: ItemsIn, background: BackgroundTasks,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """加入内容，收数组支持批量。

    请求内只做 describe + 建行（纯本地，响应即时）；正文抓取与切片丢后台，前端靠
    文档列表轮询看 pending → ready。failed 只覆盖请求阶段的错误（源不存在等），
    后台失败体现为文档 status="failed"。
    """
    kb = await _owned_kb(db, user, kb_id)
    added = duplicate = 0
    failed: list[dict] = []
    for item in body.items:
        try:
            await check_document_quota(db, kb.id, user)
            result, doc_id = await add_source_item(db, kb.id, item.source_type,
                                                  item.source_ref_id)
        except QuotaExceeded as e:
            failed.append({"source_ref_id": item.source_ref_id, "error": e.message})
            break                 # 触顶后同批剩余的必然也失败，不必逐条试
        except SourceNotFound as e:
            failed.append({"source_ref_id": item.source_ref_id, "error": str(e)})
            continue
        if result == "duplicate":
            duplicate += 1
            continue
        added += 1
        background.add_task(ingest_source_document, doc_id, item.source_type,
                            item.source_ref_id)
    return {"added": added, "duplicate": duplicate, "failed": failed}


@router.post("/{kb_id}/sources", response_model=SourceOut)
async def add_source(
    kb_id: str, body: SourceIn, background: BackgroundTasks,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """整号/信源订阅：建 KbSource 后触发后台回填。重复订阅返回已有记录。"""
    kb = await _owned_kb(db, user, kb_id)
    if body.source_type != "wechat_account":
        raise HTTPException(400, f"不支持的来源类型：{body.source_type}")
    existing = await db.scalar(
        select(KbSource).where(
            KbSource.kb_id == kb.id, KbSource.source_type == body.source_type,
            KbSource.source_ref_id == body.source_ref_id,
        )
    )
    if existing is not None:
        return _source_out(existing)
    try:
        await check_source_quota(db, user)
    except QuotaExceeded as e:
        raise HTTPException(409, e.message)
    src = KbSource(kb_id=kb.id, source_type=body.source_type,
                   source_ref_id=body.source_ref_id, display_name=body.display_name)
    db.add(src)
    await db.commit()
    background.add_task(backfill_source, src.id)
    return _source_out(src)


@router.get("/{kb_id}/sources", response_model=list[SourceOut])
async def list_sources(
    kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    kb = await _owned_kb(db, user, kb_id)
    rows = (await db.execute(
        select(KbSource).where(KbSource.kb_id == kb.id).order_by(KbSource.created_at)
    )).scalars().all()
    return [_source_out(s) for s in rows]


@router.delete("/{kb_id}/sources/{source_id}")
async def delete_source(
    kb_id: str, source_id: str, purge: bool = False,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """断开订阅。默认保留已入库文档——知识库语义是「我攒下的资料」，不该因退订而蒸发。"""
    kb = await _owned_kb(db, user, kb_id)
    try:
        sid = uuid.UUID(source_id)
    except ValueError:
        raise HTTPException(404, "订阅不存在")
    src = await db.get(KbSource, sid)
    if src is None or src.kb_id != kb.id:
        raise HTTPException(404, "订阅不存在")
    purged = 0
    if purge:
        purged = (await db.execute(
            select(func.count()).select_from(KbDocument)
            .where(KbDocument.kb_source_id == src.id)
        )).scalar_one()
        await db.execute(delete(KbDocument).where(KbDocument.kb_source_id == src.id))
    await db.delete(src)
    await db.commit()
    return {"deleted": True, "purged": purged}
```

上传端点也要加配额检查——上限管的是库的规模，不分来源。`upload_document` 里 `_owned_kb` 之后插入：

```python
    try:
        await check_document_quota(db, kb.id, user)
    except QuotaExceeded as e:
        raise HTTPException(409, e.message)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_kb_items_api.py -v`
Expected: PASS（8 个用例）

- [ ] **Step 6: 写 sources 端点测试**

创建 `backend/tests/test_kb_sources_api.py`：

```python
import asyncio
import datetime as dt
import uuid

import pytest
from sqlalchemy import func, select

from app.kb.models import KbDocument
from tests.conftest import _auth


async def _account_with_articles(db, n=2):
    from app.social.ingest import get_or_create_account
    from app.social.models import WechatArticle

    acc = await get_or_create_account(db, f"F{uuid.uuid4().hex[:8]}", "财经号")
    for i in range(n):
        db.add(WechatArticle(
            account_id=acc.id, external_id=f"a{uuid.uuid4().hex[:8]}", title=f"文章{i}",
            digest="", cover_url=None, url=f"https://mp.weixin.qq.com/s/{uuid.uuid4().hex[:6]}",
            content="正文内容足够长以便切片。" * 20,
            published_at=dt.datetime(2026, 7, i + 1, tzinfo=dt.UTC),
        ))
    await db.commit()
    return acc


@pytest.fixture
def fast_limiter(monkeypatch):
    from app.core import config
    from app.kb.ratelimit import reset_for_tests

    monkeypatch.setenv("KB_BACKFILL_DELAY_SECONDS", "0")
    config.get_settings.cache_clear()
    reset_for_tests()
    yield
    config.get_settings.cache_clear()
    reset_for_tests()


@pytest.mark.asyncio
async def test_subscribe_account_triggers_backfill(client, db_session, registered_user,
                                                   fast_limiter):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "公众号库"}, headers=h)).json()["id"]
    acc = await _account_with_articles(db_session, 2)

    r = await client.post(f"/api/kb/{kb_id}/sources", headers=h, json={
        "source_type": "wechat_account", "source_ref_id": str(acc.id),
        "display_name": "财经号"})
    assert r.status_code == 200
    assert r.json()["status"] == "pending" and r.json()["enabled"] is True

    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if len(docs) >= 2 and all(d["status"] in ("ready", "failed") for d in docs):
            break
        await asyncio.sleep(0.1)
    assert len(docs) == 2 and all(d["status"] == "ready" for d in docs)
    assert all(d["source_type"] == "wechat_article" for d in docs)

    srcs = (await client.get(f"/api/kb/{kb_id}/sources", headers=h)).json()
    assert len(srcs) == 1 and srcs[0]["status"] == "ready"


@pytest.mark.asyncio
async def test_duplicate_subscribe_returns_existing(client, db_session, registered_user,
                                                    fast_limiter):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "重复订阅"}, headers=h)).json()["id"]
    acc = await _account_with_articles(db_session, 1)
    body = {"source_type": "wechat_account", "source_ref_id": str(acc.id),
            "display_name": "财经号"}
    first = (await client.post(f"/api/kb/{kb_id}/sources", headers=h, json=body)).json()
    second = (await client.post(f"/api/kb/{kb_id}/sources", headers=h, json=body)).json()
    assert first["id"] == second["id"]
    assert len((await client.get(f"/api/kb/{kb_id}/sources", headers=h)).json()) == 1


@pytest.mark.asyncio
async def test_unsupported_source_type_is_400(client, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "x"}, headers=h)).json()["id"]
    r = await client.post(f"/api/kb/{kb_id}/sources", headers=h, json={
        "source_type": "xhs_user", "source_ref_id": str(uuid.uuid4()), "display_name": "小红书"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_unsubscribe_keeps_documents_by_default(client, db_session, registered_user,
                                                     fast_limiter):
    """取消订阅保留已入库文档；清理走显式的 purge。"""
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "保留库"}, headers=h)).json()["id"]
    acc = await _account_with_articles(db_session, 2)
    src_id = (await client.post(f"/api/kb/{kb_id}/sources", headers=h, json={
        "source_type": "wechat_account", "source_ref_id": str(acc.id),
        "display_name": "号"})).json()["id"]

    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if len(docs) >= 2:
            break
        await asyncio.sleep(0.1)

    r = (await client.delete(f"/api/kb/{kb_id}/sources/{src_id}", headers=h)).json()
    assert r == {"deleted": True, "purged": 0}
    assert len((await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()) == 2


@pytest.mark.asyncio
async def test_unsubscribe_with_purge_deletes_documents(client, db_session, registered_user,
                                                       fast_limiter):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "清理库"}, headers=h)).json()["id"]
    acc = await _account_with_articles(db_session, 2)
    src_id = (await client.post(f"/api/kb/{kb_id}/sources", headers=h, json={
        "source_type": "wechat_account", "source_ref_id": str(acc.id),
        "display_name": "号"})).json()["id"]

    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if len(docs) >= 2:
            break
        await asyncio.sleep(0.1)

    r = (await client.delete(f"/api/kb/{kb_id}/sources/{src_id}?purge=true", headers=h)).json()
    assert r["deleted"] is True and r["purged"] == 2
    assert (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json() == []


@pytest.mark.asyncio
async def test_purge_spares_manually_added_documents(client, db_session, registered_user,
                                                     fast_limiter):
    """purge 只删该订阅带进来的（kb_source_id 匹配），手动加入的不受影响。"""
    from app.news.models import NewsItem, NewsSource

    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "混合清理"}, headers=h)).json()["id"]
    acc = await _account_with_articles(db_session, 1)
    src_id = (await client.post(f"/api/kb/{kb_id}/sources", headers=h, json={
        "source_type": "wechat_account", "source_ref_id": str(acc.id),
        "display_name": "号"})).json()["id"]

    ns = NewsSource(name="s", type="sina_live", channel="news", config={})
    db_session.add(ns)
    await db_session.flush()
    item = NewsItem(source_id=ns.id, channel="news", external_id=f"n{uuid.uuid4().hex[:8]}",
                    content_hash=uuid.uuid4().hex, title="手动加的快讯", content="内容",
                    url=None, published_at=dt.datetime(2026, 7, 9, tzinfo=dt.UTC))
    db_session.add(item)
    await db_session.commit()
    await client.post(f"/api/kb/{kb_id}/items", headers=h, json={
        "items": [{"source_type": "news_item", "source_ref_id": str(item.id)}]})

    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if len(docs) >= 2:
            break
        await asyncio.sleep(0.1)

    await client.delete(f"/api/kb/{kb_id}/sources/{src_id}?purge=true", headers=h)
    left = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
    assert [d["title"] for d in left] == ["手动加的快讯"]


@pytest.mark.asyncio
async def test_sources_on_foreign_kb_is_404(client, registered_user):
    h = _auth(registered_user)
    assert (await client.get("/api/kb/00000000-0000-0000-0000-000000000000/sources",
                             headers=h)).status_code == 404
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_kb_sources_api.py tests/test_kb_items_api.py tests/test_kb_api.py tests/test_kb_flow.py -v`
Expected: 全 PASS

- [ ] **Step 8: 提交**

```bash
cd backend && uv run ruff check app tests
git add app/kb/schemas.py app/kb/router.py tests/test_kb_items_api.py tests/test_kb_sources_api.py
git commit -m "feat(kb): 内容加入、整号订阅、文档详情/删除端点"
```

---

## Task 9: 单库常驻会话

**Files:**
- Modify: `backend/app/kb/router.py`
- Test: `backend/tests/test_kb_thread_api.py`

**Interfaces:**
- Produces: `GET /api/kb/{kb_id}/thread` → `{"thread_id": str}`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_kb_thread_api.py`：

```python
import uuid

import pytest
from sqlalchemy import select

from app.threads.models import Thread
from tests.conftest import _auth


@pytest.mark.asyncio
async def test_thread_is_created_once_per_kb(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "对话库"}, headers=h)).json()["id"]

    first = (await client.get(f"/api/kb/{kb_id}/thread", headers=h)).json()["thread_id"]
    second = (await client.get(f"/api/kb/{kb_id}/thread", headers=h)).json()["thread_id"]
    assert first == second                       # 常驻，不是每次新建

    t = await db_session.get(Thread, uuid.UUID(first))
    assert t.type == "kb" and t.ref_id == uuid.UUID(kb_id)
    assert t.user_id == registered_user.id


@pytest.mark.asyncio
async def test_each_kb_gets_its_own_thread(client, registered_user):
    h = _auth(registered_user)
    kb1 = (await client.post("/api/kb", json={"name": "库A"}, headers=h)).json()["id"]
    kb2 = (await client.post("/api/kb", json={"name": "库B"}, headers=h)).json()["id"]
    t1 = (await client.get(f"/api/kb/{kb1}/thread", headers=h)).json()["thread_id"]
    t2 = (await client.get(f"/api/kb/{kb2}/thread", headers=h)).json()["thread_id"]
    assert t1 != t2


@pytest.mark.asyncio
async def test_kb_thread_absent_from_global_thread_list(client, registered_user):
    """type != "chat" 的会话不进左侧全局会话列表，与新闻助手一致。"""
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "隐藏库"}, headers=h)).json()["id"]
    tid = (await client.get(f"/api/kb/{kb_id}/thread", headers=h)).json()["thread_id"]
    listed = (await client.get("/api/threads/", headers=h)).json()
    assert tid not in [t["id"] for t in listed]


@pytest.mark.asyncio
async def test_thread_on_foreign_kb_is_404(client, registered_user):
    h = _auth(registered_user)
    r = await client.get("/api/kb/00000000-0000-0000-0000-000000000000/thread", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_thread_recreated_after_soft_delete(client, registered_user):
    """清除对话：软删后再取会得到新 id（前端据此重建 runtime 清空历史）。"""
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "清空库"}, headers=h)).json()["id"]
    old = (await client.get(f"/api/kb/{kb_id}/thread", headers=h)).json()["thread_id"]
    assert (await client.delete(f"/api/threads/{old}", headers=h)).status_code == 204
    new = (await client.get(f"/api/kb/{kb_id}/thread", headers=h)).json()["thread_id"]
    assert new != old
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_kb_thread_api.py -v`
Expected: FAIL — 404/405，路由不存在

- [ ] **Step 3: 实现**

`backend/app/kb/router.py` 追加（放在 `list_sources` 之后即可，路径三段式不与 `/{kb_id}` 冲突）：

```python
@router.get("/{kb_id}/thread")
async def get_kb_thread(
    kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """取/建该库的常驻会话。照 /api/news/thread 的做法，按 ref_id 区分到库。

    type="kb" 使其不进左侧全局会话列表（见 threads/router.py 的 list_threads）。
    """
    from app.threads.models import Thread

    kb = await _owned_kb(db, user, kb_id)
    thread = await db.scalar(
        select(Thread).where(
            Thread.user_id == user.id, Thread.type == "kb",
            Thread.ref_id == kb.id, Thread.deleted_at.is_(None),
        )
    )
    if thread is None:
        thread = Thread(user_id=user.id, title=f"{kb.name} 对话", type="kb", ref_id=kb.id)
        db.add(thread)
        await db.commit()
        await db.refresh(thread)
    return {"thread_id": str(thread.id)}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_kb_thread_api.py -v`
Expected: PASS（5 个用例）

- [ ] **Step 5: 跑全部后端测试**

Run: `cd backend && uv run pytest -q`
Expected: 全 PASS（若 `test_real_smoke.py` 因缺 API key 跳过属正常）

- [ ] **Step 6: 提交**

```bash
cd backend && uv run ruff check app tests
git add app/kb/router.py tests/test_kb_thread_api.py
git commit -m "feat(kb): 单库常驻会话端点"
```

## Task 10: 前端 API 封装

**Files:**
- Modify: `frontend/src/lib/kb.ts`
- Test: `frontend/src/lib/kb.test.ts`（扩展）

**Interfaces:**
- Consumes: Task 8/9 的端点
- Produces（`lib/kb.ts` 导出）：
  - `type KbDoc = { id; title; filename: string | null; status; chunk_count; error: string | null; source_type; source_url: string | null; published_at: string | null }`（**注意 `title` 新增、`filename` 变可空**）
  - `type KbDocDetail = KbDoc & { text: string | null }`
  - `type KbSource = { id; source_type; source_ref_id; display_name; status; enabled; error: string | null; last_synced_at: string | null }`
  - `type AddItemsResult = { added: number; duplicate: number; failed: { source_ref_id: string; error: string }[] }`
  - `fetchDocs(kbId, opts?: { limit?: number; offset?: number }): Promise<KbDoc[]>`
  - `fetchDoc(kbId, docId): Promise<KbDocDetail>`
  - `deleteDoc(kbId, docId): Promise<void>`
  - `addKbItems(kbId, items: { source_type: string; source_ref_id: string }[]): Promise<AddItemsResult>`
  - `addKbSource(kbId, body: { source_type; source_ref_id; display_name }): Promise<KbSource>`
  - `fetchKbSources(kbId): Promise<KbSource[]>`
  - `deleteKbSource(kbId, sourceId, purge?: boolean): Promise<void>`
  - `fetchKbThreadId(kbId): Promise<string>`
  - `deleteKb(kbId): Promise<void>`

- [ ] **Step 1: 写失败测试**

在 `frontend/src/lib/kb.test.ts` 的 `describe` 块内追加：

```typescript
  it("fetchDocs 带分页参数并解析新字段", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(
        JSON.stringify([{
          id: "d1", title: "某篇文章", filename: null, status: "ready", chunk_count: 3,
          error: null, source_type: "wechat_article",
          source_url: "https://mp.weixin.qq.com/s/x", published_at: "2026-07-01T00:00:00Z",
        }]),
        { status: 200 },
      ),
    );
    const docs = await fetchDocs("k1", { limit: 20, offset: 40 });
    expect(docs[0].title).toBe("某篇文章");
    expect(docs[0].filename).toBeNull();
    expect(docs[0].source_type).toBe("wechat_article");
    expect(spy.mock.calls[0][0]).toBe("/api/kb/k1/documents?limit=20&offset=40");
  });

  it("fetchDoc 返回入库文本快照", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({
        id: "d1", title: "t", filename: null, status: "ready", chunk_count: 1, error: null,
        source_type: "news_item", source_url: null, published_at: null, text: "正文快照",
      }), { status: 200 }),
    );
    const d = await fetchDoc("k1", "d1");
    expect(d.text).toBe("正文快照");
    expect(spy.mock.calls[0][0]).toBe("/api/kb/k1/documents/d1");
  });

  it("deleteDoc 发 DELETE", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await deleteDoc("k1", "d1");
    expect(spy).toHaveBeenCalledWith("/api/kb/k1/documents/d1", { method: "DELETE" });
  });

  it("addKbItems 提交数组并解析结果", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({
        added: 2, duplicate: 1, failed: [{ source_ref_id: "x", error: "快讯不存在" }],
      }), { status: 200 }),
    );
    const r = await addKbItems("k1", [
      { source_type: "news_item", source_ref_id: "a" },
      { source_type: "news_item", source_ref_id: "b" },
    ]);
    expect(r.added).toBe(2);
    expect(r.duplicate).toBe(1);
    expect(r.failed[0].error).toBe("快讯不存在");
    const [path, init] = spy.mock.calls[0];
    expect(path).toBe("/api/kb/k1/items");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string).items).toHaveLength(2);
  });

  it("addKbSource 提交订阅", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({
        id: "s1", source_type: "wechat_account", source_ref_id: "acc-1",
        display_name: "财经号", status: "pending", enabled: true, error: null,
        last_synced_at: null,
      }), { status: 200 }),
    );
    const s = await addKbSource("k1", {
      source_type: "wechat_account", source_ref_id: "acc-1", display_name: "财经号",
    });
    expect(s.status).toBe("pending");
    expect(spy.mock.calls[0][0]).toBe("/api/kb/k1/sources");
  });

  it("deleteKbSource 默认不 purge，显式传 true 才带参数", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await deleteKbSource("k1", "s1");
    expect(spy).toHaveBeenCalledWith("/api/kb/k1/sources/s1?purge=false", { method: "DELETE" });
    await deleteKbSource("k1", "s1", true);
    expect(spy).toHaveBeenLastCalledWith("/api/kb/k1/sources/s1?purge=true", { method: "DELETE" });
  });

  it("fetchKbThreadId 取常驻会话 id", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({ thread_id: "t-1" }), { status: 200 }),
    );
    expect(await fetchKbThreadId("k1")).toBe("t-1");
  });

  it("接口失败时抛错而不是静默返回空", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(new Response("nope", { status: 409 }));
    await expect(addKbItems("k1", [{ source_type: "news_item", source_ref_id: "a" }]))
      .rejects.toThrow();
  });
```

文件顶部 import 改为：

```typescript
import { describe, expect, it, vi } from "vitest";
import * as api from "./api";
import {
  addKbItems,
  addKbSource,
  createKb,
  deleteDoc,
  deleteKbSource,
  fetchDoc,
  fetchDocs,
  fetchKbSources,
  fetchKbThreadId,
  fetchKbs,
  fetchSubscribed,
  subscribeKb,
  uploadDoc,
} from "./kb";
```

`fetchKbSources` 在上面的用例里没直接测，但导入它可让 TS 在函数缺失时报错。若 oxlint 抱怨未使用，给它补一个用例：

```typescript
  it("fetchKbSources 解析列表", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify([{
        id: "s1", source_type: "wechat_account", source_ref_id: "a", display_name: "号",
        status: "ready", enabled: true, error: null, last_synced_at: "2026-08-01T00:00:00Z",
      }]), { status: 200 }),
    );
    const rows = await fetchKbSources("k1");
    expect(rows[0].display_name).toBe("号");
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/lib/kb.test.ts`
Expected: FAIL — `addKbItems is not a function` / 导入报错

- [ ] **Step 3: 实现**

`frontend/src/lib/kb.ts` 整个文件替换为：

```typescript
import { apiFetch } from "./api";

export type Kb = { id: string; name: string; is_shared: boolean; doc_count: number };

export type KbDoc = {
  id: string;
  title: string;
  filename: string | null;      // 仅上传文档有值
  status: string;
  chunk_count: number;
  error: string | null;
  source_type: string;          // upload | wechat_article | news_item
  source_url: string | null;
  published_at: string | null;  // 原始发布时间，索引按它倒序
};

export type KbDocDetail = KbDoc & { text: string | null };

export type KbSource = {
  id: string;
  source_type: string;
  source_ref_id: string;
  display_name: string;
  status: string;               // pending | syncing | ready | failed | limited
  enabled: boolean;
  error: string | null;
  last_synced_at: string | null;
};

export type AddItemsResult = {
  added: number;
  duplicate: number;
  failed: { source_ref_id: string; error: string }[];
};

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<T>;
}

async function ok(r: Response): Promise<void> {
  if (!r.ok) throw new Error(await r.text());
}

export async function fetchKbs(): Promise<Kb[]> {
  return json(await apiFetch("/api/kb"));
}

export async function createKb(name: string): Promise<Kb> {
  return json(await apiFetch("/api/kb", {
    method: "POST",
    body: JSON.stringify({ name }),
    headers: { "Content-Type": "application/json" },
  }));
}

export async function deleteKb(kbId: string): Promise<void> {
  return ok(await apiFetch(`/api/kb/${kbId}`, { method: "DELETE" }));
}

export async function uploadDoc(kbId: string, file: File): Promise<void> {
  const fd = new FormData();
  fd.append("file", file);
  return ok(await apiFetch(`/api/kb/${kbId}/documents`, { method: "POST", body: fd }));
}

export async function fetchDocs(
  kbId: string,
  opts: { limit?: number; offset?: number } = {},
): Promise<KbDoc[]> {
  const p = new URLSearchParams();
  p.set("limit", String(opts.limit ?? 50));
  p.set("offset", String(opts.offset ?? 0));
  return json(await apiFetch(`/api/kb/${kbId}/documents?${p.toString()}`));
}

export async function fetchDoc(kbId: string, docId: string): Promise<KbDocDetail> {
  return json(await apiFetch(`/api/kb/${kbId}/documents/${docId}`));
}

export async function deleteDoc(kbId: string, docId: string): Promise<void> {
  return ok(await apiFetch(`/api/kb/${kbId}/documents/${docId}`, { method: "DELETE" }));
}

export async function addKbItems(
  kbId: string,
  items: { source_type: string; source_ref_id: string }[],
): Promise<AddItemsResult> {
  return json(await apiFetch(`/api/kb/${kbId}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  }));
}

export async function addKbSource(
  kbId: string,
  body: { source_type: string; source_ref_id: string; display_name: string },
): Promise<KbSource> {
  return json(await apiFetch(`/api/kb/${kbId}/sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }));
}

export async function fetchKbSources(kbId: string): Promise<KbSource[]> {
  return json(await apiFetch(`/api/kb/${kbId}/sources`));
}

export async function deleteKbSource(
  kbId: string,
  sourceId: string,
  purge = false,
): Promise<void> {
  return ok(await apiFetch(`/api/kb/${kbId}/sources/${sourceId}?purge=${purge}`, {
    method: "DELETE",
  }));
}

export async function fetchKbThreadId(kbId: string): Promise<string> {
  const data = await json<{ thread_id: string }>(await apiFetch(`/api/kb/${kbId}/thread`));
  return data.thread_id;
}

// 清除对话：软删当前会话，再取一个新的（GET /thread 会自动重建）。与 news 同做法。
export async function clearKbThread(kbId: string, threadId: string): Promise<string> {
  await ok(await apiFetch(`/api/threads/${threadId}`, { method: "DELETE" }));
  return fetchKbThreadId(kbId);
}

export async function shareKb(kbId: string): Promise<{ share_slug: string }> {
  return json(await apiFetch(`/api/kb/${kbId}/share`, { method: "POST" }));
}

export async function subscribeKb(slug: string): Promise<{ kb_id: string; name: string }> {
  return json(await apiFetch(`/api/kb/subscribe/${slug}`, { method: "POST" }));
}

export async function fetchSubscribed(): Promise<{ id: string; name: string }[]> {
  return json(await apiFetch("/api/kb/subscribed"));
}
```

原来 `uploadDoc` 抛的是 `new Error("upload failed")`，改成透传后端文案后，配额触顶（409）的提示才能显示出来。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/lib/kb.test.ts && npx tsc -b`
Expected: PASS；`tsc` 会在 `KbPanel.tsx` 报 `d.filename` 类型错（下一个任务修）——若阻塞，先跑 vitest，`tsc` 留到 Task 11 末尾一起过。

- [ ] **Step 5: 提交**

```bash
cd frontend && npm run lint
git add src/lib/kb.ts src/lib/kb.test.ts
git commit -m "feat(kb): 前端 API 封装 — 内容加入、订阅源、文档详情"
```

---

## Task 11: KB 面板三栏重写

```
┌──────────┬───────────────┬──────────────┐
│ 库列表   │ 内容索引      │ 详情          │
│          │               │ ┌──────────┐ │
│          │               │ │ 对话栏   │ │
│          │               │ └──────────┘ │
└──────────┴───────────────┴──────────────┘
```

**Files:**
- Modify: `frontend/src/chat/RuntimeProvider.tsx`
- Rewrite: `frontend/src/panels/KbPanel.tsx`
- Create: `frontend/src/panels/kb/KbList.tsx`
- Create: `frontend/src/panels/kb/KbDocumentIndex.tsx`
- Create: `frontend/src/panels/kb/KbDocumentDetail.tsx`
- Create: `frontend/src/panels/kb/KbAssistant.tsx`
- Test: `frontend/src/panels/KbPanel.test.tsx`

**Interfaces:**
- Consumes: Task 10 的全部导出
- Produces:
  - `RuntimeProvider` 新增可选 prop `mountedKbIds?: string[]` — 传入时覆盖全局 store，不传时行为不变
  - `KbList({ selectedId, onSelect })`
  - `KbDocumentIndex({ kbId, selectedDocId, onSelect })`
  - `KbDocumentDetail({ kbId, docId })`
  - `KbAssistant({ kbId, collapsed, onToggle })`

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/panels/KbPanel.test.tsx`：

```tsx
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/kb", () => ({
  fetchKbs: vi.fn(async () => [
    { id: "k1", name: "研报库", is_shared: false, doc_count: 2 },
    { id: "k2", name: "快讯库", is_shared: true, doc_count: 0 },
  ]),
  createKb: vi.fn(),
  deleteKb: vi.fn(),
  shareKb: vi.fn(async () => ({ share_slug: "abc123" })),
  subscribeKb: vi.fn(),
  uploadDoc: vi.fn(),
  fetchDocs: vi.fn(async (kbId: string) =>
    kbId === "k1"
      ? [
          {
            id: "d1", title: "茅台年报解读", filename: null, status: "ready", chunk_count: 5,
            error: null, source_type: "wechat_article",
            source_url: "https://mp.weixin.qq.com/s/x", published_at: "2026-07-20T02:00:00Z",
          },
          {
            id: "d2", title: "手册.pdf", filename: "手册.pdf", status: "processing",
            chunk_count: 0, error: null, source_type: "upload", source_url: null,
            published_at: null,
          },
        ]
      : [],
  ),
  fetchDoc: vi.fn(async () => ({
    id: "d1", title: "茅台年报解读", filename: null, status: "ready", chunk_count: 5,
    error: null, source_type: "wechat_article",
    source_url: "https://mp.weixin.qq.com/s/x", published_at: "2026-07-20T02:00:00Z",
    text: "这是入库时的文本快照内容。",
  })),
  deleteDoc: vi.fn(async () => undefined),
  fetchKbSources: vi.fn(async () => []),
  deleteKbSource: vi.fn(),
  fetchKbThreadId: vi.fn(async () => "t-kb-1"),
  clearKbThread: vi.fn(async () => "t-kb-2"),
  fetchSubscribed: vi.fn(async () => []),
}));

// 对话栏依赖 assistant-ui 运行时，单测里替换为占位，只验证挂载参数
vi.mock("@/panels/kb/KbAssistant", () => ({
  default: ({ kbId }: { kbId: string }) => <div data-testid="kb-assistant">{kbId}</div>,
}));

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return import("./KbPanel").then(({ default: KbPanel }) =>
    render(
      <QueryClientProvider client={qc}>
        <KbPanel />
      </QueryClientProvider>,
    ),
  );
}

describe("KbPanel 三栏", () => {
  afterEach(() => vi.clearAllMocks());

  it("列出知识库，默认选中第一个并加载其内容索引", async () => {
    await renderPanel();
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    expect(screen.getByText("快讯库")).toBeTruthy();
    await waitFor(() => expect(screen.getByText("茅台年报解读")).toBeTruthy());
  });

  it("切换知识库会换掉内容索引", async () => {
    await renderPanel();
    await waitFor(() => expect(screen.getByText("茅台年报解读")).toBeTruthy());
    fireEvent.click(screen.getByText("快讯库"));
    await waitFor(() => expect(screen.queryByText("茅台年报解读")).toBeNull());
    expect(screen.getByText("暂无内容")).toBeTruthy();
  });

  it("点内容项后详情区展示入库文本快照与原文链接", async () => {
    await renderPanel();
    await waitFor(() => expect(screen.getByText("茅台年报解读")).toBeTruthy());
    fireEvent.click(screen.getByText("茅台年报解读"));
    await waitFor(() =>
      expect(screen.getByText("这是入库时的文本快照内容。")).toBeTruthy(),
    );
    const link = screen.getByRole("link", { name: /原文/ });
    expect(link.getAttribute("href")).toBe("https://mp.weixin.qq.com/s/x");
  });

  it("处理中的文档显示状态徽章", async () => {
    await renderPanel();
    await waitFor(() => expect(screen.getByText("手册.pdf")).toBeTruthy());
    expect(screen.getByText("处理中")).toBeTruthy();
  });

  it("对话栏默认折叠，展开后把当前库 id 传给助手", async () => {
    await renderPanel();
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    expect(screen.queryByTestId("kb-assistant")).toBeNull();
    fireEvent.click(screen.getByTestId("kb-chat-toggle"));
    await waitFor(() => {
      expect(screen.getByTestId("kb-assistant").textContent).toBe("k1");
    });
  });

  it("删除内容后从索引中消失", async () => {
    const kb = await import("@/lib/kb");
    await renderPanel();
    await waitFor(() => expect(screen.getByText("茅台年报解读")).toBeTruthy());
    vi.mocked(kb.fetchDocs).mockResolvedValue([]);
    fireEvent.click(screen.getByTestId("kb-doc-delete-d1"));
    await waitFor(() => expect(kb.deleteDoc).toHaveBeenCalledWith("k1", "d1"));
  });

  it("没有知识库时给出引导文案", async () => {
    const kb = await import("@/lib/kb");
    vi.mocked(kb.fetchKbs).mockResolvedValue([]);
    await renderPanel();
    await waitFor(() =>
      expect(screen.getByText("还没有知识库，先建一个吧")).toBeTruthy(),
    );
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/panels/KbPanel.test.tsx`
Expected: FAIL — 找不到 `./KbPanel` 的三栏结构 / `kb-chat-toggle` 不存在

- [ ] **Step 3: RuntimeProvider 加 mountedKbIds prop**

`frontend/src/chat/RuntimeProvider.tsx`：`RuntimeProvider` 与 `RuntimeInner` 的 props 各加一项，并把它透传下去。

`RuntimeProvider` 的签名与转发：

```tsx
export function RuntimeProvider({
  threadId,
  children,
  onSendResponse,
  onFinish,
  initialMessage,
  mountedKbIds,
}: {
  threadId: string;
  children: ReactNode;
  onSendResponse?: (status: number) => void;
  onFinish?: () => void;
  initialMessage?: string | null;
  // 传入时覆盖全局挂载 store。KB 面板的单库对话用它锁定为当前库，
  // 否则用户在聊天面板勾选的库会漏进 KB 对话。
  mountedKbIds?: string[];
}) {
```

`return` 的 `<RuntimeInner ...>` 加 `mountedKbIds={mountedKbIds}`。

`RuntimeInner` 同样加这个 prop，并把 `body` 改为：

```tsx
    body: () =>
      Promise.resolve({
        threadId,
        mountedKbIds: mountedKbIds ?? getMountedKbIds(),
      }),
```

- [ ] **Step 4: 写 KbList.tsx**

创建 `frontend/src/panels/kb/KbList.tsx`：

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createKb, fetchKbs, shareKb, subscribeKb, type Kb } from "@/lib/kb";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export const kbKey = ["kb"] as const;

export default function KbList({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const { data: kbs = [], isLoading, isError } = useQuery({ queryKey: kbKey, queryFn: fetchKbs });

  const create = useMutation({
    mutationFn: () => createKb(name.trim()),
    onSuccess: (kb) => {
      setName("");
      qc.invalidateQueries({ queryKey: kbKey });
      onSelect(kb.id);
    },
  });

  const subscribe = useMutation({
    mutationFn: () => subscribeKb(slug.trim()),
    onSuccess: (r) => {
      setSlug("");
      setMsg(`已订阅「${r.name}」`);
      qc.invalidateQueries({ queryKey: kbKey });
    },
    onError: () => setMsg("订阅失败：分享码无效或已关闭"),
  });

  const share = useMutation({
    mutationFn: (id: string) => shareKb(id),
    onSuccess: (r) => {
      setMsg(`分享码：${r.share_slug}`);
      qc.invalidateQueries({ queryKey: kbKey });
    },
  });

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 space-y-2 border-b p-3">
        <div className="flex gap-1.5">
          <Input
            placeholder="新建知识库"
            className="h-8 text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && name.trim()) create.mutate();
            }}
          />
          <Button
            size="sm"
            data-testid="kb-create"
            disabled={!name.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            建库
          </Button>
        </div>
        <div className="flex gap-1.5">
          <Input
            placeholder="分享码订阅"
            className="h-8 text-sm"
            value={slug}
            onChange={(e) => {
              setSlug(e.target.value);
              setMsg(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && slug.trim()) subscribe.mutate();
            }}
          />
          <Button
            size="sm"
            variant="outline"
            data-testid="kb-subscribe"
            disabled={!slug.trim() || subscribe.isPending}
            onClick={() => subscribe.mutate()}
          >
            订阅
          </Button>
        </div>
        {msg && <p className="break-all text-xs text-muted-foreground">{msg}</p>}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {isLoading && <p className="px-1 text-sm text-muted-foreground">加载中…</p>}
        {isError && <p className="px-1 text-sm text-destructive">加载知识库失败</p>}
        {!isLoading && !isError && kbs.length === 0 && (
          <p className="px-1 text-sm text-muted-foreground">还没有知识库，先建一个吧</p>
        )}
        <ul className="space-y-0.5">
          {kbs.map((kb: Kb) => (
            <li key={kb.id}>
              <button
                type="button"
                data-testid={`kb-item-${kb.id}`}
                onClick={() => onSelect(kb.id)}
                className={cn(
                  "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent/50",
                  selectedId === kb.id && "bg-accent font-medium",
                )}
              >
                <span className="min-w-0 flex-1 truncate">{kb.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground">{kb.doc_count}</span>
              </button>
              {selectedId === kb.id && (
                <button
                  type="button"
                  data-testid={`kb-share-${kb.id}`}
                  disabled={share.isPending}
                  onClick={() => share.mutate(kb.id)}
                  className="ml-2 mt-0.5 text-xs text-muted-foreground hover:text-foreground"
                >
                  {kb.is_shared ? "查看分享" : "生成分享"}
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: 写 KbDocumentIndex.tsx**

创建 `frontend/src/panels/kb/KbDocumentIndex.tsx`：

```tsx
import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, MessageSquare, Newspaper, Trash2, Upload } from "lucide-react";
import { deleteDoc, fetchDocs, uploadDoc, type KbDoc } from "@/lib/kb";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<string, string> = {
  pending: "排队中",
  processing: "处理中",
  ready: "就绪",
  failed: "失败",
};

const SOURCE_ICON: Record<string, typeof FileText> = {
  upload: FileText,
  wechat_article: MessageSquare,
  news_item: Newspaper,
};

function StatusBadge({ status }: { status: string }) {
  if (status === "ready") return null;   // 就绪是常态，不占视觉
  const failed = status === "failed";
  return (
    <span
      className={cn(
        "shrink-0 rounded-md px-1.5 py-0.5 text-xs font-medium",
        failed ? "bg-destructive/10 text-destructive" : "bg-muted text-muted-foreground",
      )}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export default function KbDocumentIndex({
  kbId,
  selectedDocId,
  onSelect,
}: {
  kbId: string;
  selectedDocId: string | null;
  onSelect: (docId: string) => void;
}) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const docsKey = ["kb-docs", kbId] as const;

  const { data: docs = [], isLoading } = useQuery({
    queryKey: docsKey,
    queryFn: () => fetchDocs(kbId),
    // 有在处理的文档就轮询，全部落定后停下（沿用旧 DocList 的做法）
    refetchInterval: (query) => {
      const list = (query.state.data as KbDoc[] | undefined) ?? [];
      return list.some((d) => d.status === "pending" || d.status === "processing") ? 1500 : false;
    },
  });

  const upload = useMutation({
    mutationFn: (file: File) => uploadDoc(kbId, file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: docsKey });
      qc.invalidateQueries({ queryKey: ["kb"] });
    },
  });

  const remove = useMutation({
    mutationFn: (docId: string) => deleteDoc(kbId, docId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: docsKey });
      qc.invalidateQueries({ queryKey: ["kb"] });
    },
  });

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b px-3 py-2">
        <span className="text-xs font-medium text-muted-foreground">内容（{docs.length}）</span>
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.md,.pdf"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload.mutate(f);
            e.target.value = "";
          }}
        />
        <Button
          size="sm"
          variant="outline"
          className="h-7"
          data-testid={`kb-upload-${kbId}`}
          disabled={upload.isPending}
          onClick={() => fileRef.current?.click()}
        >
          <Upload className="size-3.5" />
          上传
        </Button>
      </div>

      {upload.isError && (
        <p className="border-b px-3 py-1.5 text-xs text-destructive" role="alert">
          {String(upload.error)}
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {isLoading && <p className="px-1.5 text-sm text-muted-foreground">加载中…</p>}
        {!isLoading && docs.length === 0 && (
          <p className="px-1.5 text-sm text-muted-foreground">暂无内容</p>
        )}
        <ul className="space-y-0.5">
          {docs.map((d) => {
            const Icon = SOURCE_ICON[d.source_type] ?? FileText;
            return (
              <li
                key={d.id}
                className={cn(
                  "group flex items-center gap-1.5 rounded px-1.5 py-1 hover:bg-accent/50",
                  selectedDocId === d.id && "bg-accent",
                )}
              >
                <Icon className="size-3.5 shrink-0 text-muted-foreground" />
                <button
                  type="button"
                  onClick={() => onSelect(d.id)}
                  className="min-w-0 flex-1 truncate text-left text-sm"
                  title={d.title}
                >
                  {d.title}
                </button>
                {d.published_at && (
                  <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                    {new Date(d.published_at).toLocaleDateString("zh-CN", {
                      month: "2-digit",
                      day: "2-digit",
                    })}
                  </span>
                )}
                <StatusBadge status={d.status} />
                <button
                  type="button"
                  data-testid={`kb-doc-delete-${d.id}`}
                  aria-label={`删除 ${d.title}`}
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(d.id)}
                  className="shrink-0 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: 写 KbDocumentDetail.tsx**

创建 `frontend/src/panels/kb/KbDocumentDetail.tsx`：

```tsx
import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { fetchDoc } from "@/lib/kb";

const SOURCE_LABEL: Record<string, string> = {
  upload: "上传文档",
  wechat_article: "微信公众号",
  news_item: "7x24 快讯",
};

export default function KbDocumentDetail({
  kbId,
  docId,
}: {
  kbId: string;
  docId: string | null;
}) {
  const { data: doc, isLoading, isError } = useQuery({
    queryKey: ["kb-doc", kbId, docId],
    queryFn: () => fetchDoc(kbId, docId as string),
    enabled: docId !== null,
  });

  if (docId === null) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-sm text-muted-foreground">
        选择左侧内容查看详情
      </div>
    );
  }
  if (isLoading) {
    return <div className="p-5 text-sm text-muted-foreground">加载中…</div>;
  }
  if (isError || !doc) {
    return <div className="p-5 text-sm text-destructive">加载内容失败</div>;
  }

  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <h2 className="text-lg font-semibold leading-snug">{doc.title}</h2>
      <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>{SOURCE_LABEL[doc.source_type] ?? doc.source_type}</span>
        {doc.published_at && (
          <span className="tabular-nums">{new Date(doc.published_at).toLocaleString("zh-CN")}</span>
        )}
        {doc.status === "ready" && <span>{doc.chunk_count} 片</span>}
        {doc.source_url && (
          <a
            href={doc.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-0.5 text-primary hover:underline"
          >
            原文
            <ExternalLink className="size-3" />
          </a>
        )}
      </div>

      {doc.status === "failed" && (
        <p className="mt-4 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          处理失败：{doc.error}
        </p>
      )}

      {/* 展示入库时的文本快照，不回源重抓：检索命中的就是这份文本，
          展示与检索必须一致，否则用户会看到「AI 引用的和我看到的不一样」。 */}
      <pre className="mt-4 max-w-[65ch] whitespace-pre-wrap font-sans text-sm leading-7">
        {doc.text ?? (doc.status === "ready" ? "（无正文）" : "正在处理…")}
      </pre>
    </div>
  );
}
```

- [ ] **Step 7: 写 KbAssistant.tsx**

创建 `frontend/src/panels/kb/KbAssistant.tsx`：

```tsx
import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { RuntimeProvider } from "@/chat/RuntimeProvider";
import { Thread } from "@/chat/Thread";
import { clearKbThread, fetchKbThreadId } from "@/lib/kb";

// 单库对话：后端路径与普通聊天完全相同，只是把挂载集合锁定为当前库。
// 每库一个 type="kb" 的常驻会话，折叠/切库/切面板回来历史都还在。
export default function KbAssistant({ kbId }: { kbId: string }) {
  const [threadId, setThreadId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setThreadId(null);
    fetchKbThreadId(kbId)
      .then((id) => {
        if (alive) setThreadId(id);
      })
      .catch(console.error);
    return () => {
      alive = false;
    };
  }, [kbId]);

  const handleClear = async () => {
    if (!threadId || !confirm("清除当前对话记录？此操作不可撤销。")) return;
    try {
      setThreadId(await clearKbThread(kbId, threadId));
    } catch (e) {
      console.error(e);
    }
  };

  if (!threadId) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        正在加载对话…
      </div>
    );
  }

  return (
    // key 变化时重建 runtime：切库或清除对话都会换 threadId → 历史随之刷新
    <RuntimeProvider key={threadId} threadId={threadId} mountedKbIds={[kbId]}>
      <div className="flex h-full flex-col">
        <div className="flex shrink-0 items-center justify-between border-b px-3 py-1.5">
          <span className="text-xs text-muted-foreground">仅检索当前知识库</span>
          <button
            type="button"
            onClick={handleClear}
            title="清除对话"
            aria-label="清除对话"
            data-testid="kb-clear-chat"
            className="rounded-md border border-border p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <Trash2 className="size-3" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-hidden">
          <Thread />
        </div>
      </div>
    </RuntimeProvider>
  );
}
```

- [ ] **Step 8: 重写 KbPanel.tsx**

`frontend/src/panels/KbPanel.tsx` 整个文件替换为：

```tsx
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { MessageSquare } from "lucide-react";
import { fetchKbs } from "@/lib/kb";
import KbAssistant from "@/panels/kb/KbAssistant";
import KbDocumentDetail from "@/panels/kb/KbDocumentDetail";
import KbDocumentIndex from "@/panels/kb/KbDocumentIndex";
import KbList from "@/panels/kb/KbList";
import { cn } from "@/lib/utils";

// 三栏：库列表 → 内容索引 → 详情（详情下方挂可折叠对话栏）
export default function KbPanel() {
  const [kbId, setKbId] = useState<string | null>(null);
  const [docId, setDocId] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);

  const { data: kbs = [] } = useQuery({ queryKey: ["kb"], queryFn: fetchKbs });

  // 首次加载完成后默认选中第一个库，省掉一次点击
  useEffect(() => {
    if (kbId === null && kbs.length > 0) setKbId(kbs[0].id);
  }, [kbId, kbs]);

  return (
    <div className="flex h-full min-h-0">
      <aside className="w-56 shrink-0 border-r">
        <KbList
          selectedId={kbId}
          onSelect={(id) => {
            setKbId(id);
            setDocId(null);      // 切库后原文档不属于新库，清掉选中
          }}
        />
      </aside>

      {kbId === null ? (
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
          选择或新建一个知识库
        </div>
      ) : (
        <>
          <section className="w-72 shrink-0 border-r">
            <KbDocumentIndex kbId={kbId} selectedDocId={docId} onSelect={setDocId} />
          </section>

          <section className="flex min-w-0 flex-1 flex-col">
            <div className="flex shrink-0 items-center justify-end border-b px-3 py-1.5">
              <button
                type="button"
                data-testid="kb-chat-toggle"
                onClick={() => setChatOpen((v) => !v)}
                className={cn(
                  "flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-accent",
                  chatOpen && "bg-accent",
                )}
              >
                <MessageSquare className="size-3.5" />
                {chatOpen ? "收起对话" : "与本库对话"}
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-hidden">
              <KbDocumentDetail kbId={kbId} docId={docId} />
            </div>
            {chatOpen && (
              <div className="h-2/5 min-h-0 shrink-0 border-t">
                <KbAssistant kbId={kbId} />
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 9: 在内容索引顶部显示订阅源状态**

后端订阅触顶时把 `KbSource.status` 置为 `"limited"`，同步失败置 `"failed"`。这些必须在面板上可见，不能静默丢弃（spec 的失败模式表要求）。

`frontend/src/panels/kb/KbDocumentIndex.tsx` 顶部的 import 补：

```tsx
import { deleteKbSource, deleteDoc, fetchDocs, fetchKbSources, uploadDoc,
         type KbDoc, type KbSource } from "@/lib/kb";
```

在 `remove` mutation 之后加：

```tsx
  const sourcesKey = ["kb-sources", kbId] as const;
  const { data: sources = [] } = useQuery({
    queryKey: sourcesKey,
    queryFn: () => fetchKbSources(kbId),
    // 同步中的源会变状态，轮询到落定为止
    refetchInterval: (query) => {
      const list = (query.state.data as KbSource[] | undefined) ?? [];
      return list.some((s) => s.status === "pending" || s.status === "syncing") ? 3000 : false;
    },
  });

  const unsubscribe = useMutation({
    mutationFn: ({ id, purge }: { id: string; purge: boolean }) =>
      deleteKbSource(kbId, id, purge),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: sourcesKey });
      qc.invalidateQueries({ queryKey: docsKey });
      qc.invalidateQueries({ queryKey: ["kb"] });
    },
  });
```

在顶部工具栏 `</div>`（含上传按钮的那个）之后、`upload.isError` 之前插入订阅源区块：

```tsx
      {sources.length > 0 && (
        <ul className="shrink-0 border-b px-3 py-1.5 space-y-1">
          {sources.map((s) => (
            <li key={s.id} className="flex items-center gap-1.5 text-xs">
              <span className="min-w-0 flex-1 truncate" title={s.display_name}>
                订阅：{s.display_name}
              </span>
              {SOURCE_STATUS[s.status] && (
                <span
                  className={cn(
                    "shrink-0 rounded px-1 py-0.5",
                    s.status === "limited" || s.status === "failed"
                      ? "bg-destructive/10 text-destructive"
                      : "bg-muted text-muted-foreground",
                  )}
                  title={s.error ?? undefined}
                >
                  {SOURCE_STATUS[s.status]}
                </span>
              )}
              <button
                type="button"
                data-testid={`kb-source-remove-${s.id}`}
                aria-label={`断开订阅 ${s.display_name}`}
                disabled={unsubscribe.isPending}
                onClick={() => {
                  // 默认保留已入库文档——知识库是「我攒下的资料」，不该因退订而蒸发
                  const purge = confirm(
                    `断开「${s.display_name}」的订阅。\n\n确定 = 同时删除该订阅带进来的文档\n取消 = 保留已入库文档`,
                  );
                  unsubscribe.mutate({ id: s.id, purge });
                }}
                className="shrink-0 text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
```

文件里 `STATUS_LABEL` 旁边加订阅源状态文案：

```tsx
const SOURCE_STATUS: Record<string, string> = {
  pending: "等待同步",
  syncing: "同步中",
  failed: "同步失败",
  limited: "已达上限，停止入库",
  // ready 不显示——就绪是常态
};
```

对应的测试追加到 `frontend/src/panels/KbPanel.test.tsx`：

```tsx
  it("订阅源触顶时在面板上给出可见提示", async () => {
    const kb = await import("@/lib/kb");
    vi.mocked(kb.fetchKbSources).mockResolvedValue([
      {
        id: "s1", source_type: "wechat_account", source_ref_id: "acc-1",
        display_name: "财经号", status: "limited", enabled: true,
        error: "该知识库已达 2000 篇文档上限", last_synced_at: "2026-08-01T00:00:00Z",
      },
    ]);
    await renderPanel();
    await waitFor(() => expect(screen.getByText("订阅：财经号")).toBeTruthy());
    expect(screen.getByText("已达上限，停止入库")).toBeTruthy();
  });

  it("断开订阅时询问是否连带删除文档", async () => {
    const kb = await import("@/lib/kb");
    vi.mocked(kb.fetchKbSources).mockResolvedValue([
      {
        id: "s1", source_type: "wechat_account", source_ref_id: "acc-1",
        display_name: "财经号", status: "ready", enabled: true, error: null,
        last_synced_at: null,
      },
    ]);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    await renderPanel();
    await waitFor(() => expect(screen.getByText("订阅：财经号")).toBeTruthy());
    fireEvent.click(screen.getByTestId("kb-source-remove-s1"));
    await waitFor(() =>
      expect(kb.deleteKbSource).toHaveBeenCalledWith("k1", "s1", false),
    );
    confirmSpy.mockRestore();
  });
```

`KbPanel.test.tsx` 的 `vi.mock("@/lib/kb", ...)` 里 `fetchKbSources` 默认返回 `[]`，已在 Step 1 的 mock 中包含。

- [ ] **Step 10: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/panels/KbPanel.test.tsx && npx tsc -b && npm run lint`
Expected: 全 PASS（9 个用例）

- [ ] **Step 11: 提交**

```bash
cd frontend
git add src/panels/KbPanel.tsx src/panels/kb/ src/panels/KbPanel.test.tsx src/chat/RuntimeProvider.tsx
git commit -m "feat(kb): KB 面板三栏重写 + 单库对话栏"
```

---

## Task 12: 内容加入接入点

**Files:**
- Create: `frontend/src/components/AddToKbDialog.tsx`
- Modify: `frontend/src/panels/SocialPanel.tsx`
- Modify: `frontend/src/panels/NewsAssistant.tsx`
- Test: `frontend/src/components/AddToKbDialog.test.tsx`

**Interfaces:**
- Consumes: Task 10 的 `fetchKbs` / `createKb` / `addKbItems` / `addKbSource`
- Produces:
  - `AddToKbDialog({ open, onClose, mode, items, source, title })`
    - `mode: "items" | "source"`
    - `items?: { source_type: string; source_ref_id: string }[]` — `mode="items"` 时必填
    - `source?: { source_type: string; source_ref_id: string; display_name: string }` — `mode="source"` 时必填
    - `title?: string` — 弹窗标题，默认按 mode 取「加入知识库」/「整号订阅到知识库」

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/components/AddToKbDialog.test.tsx`：

```tsx
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/kb", () => ({
  fetchKbs: vi.fn(async () => [
    { id: "k1", name: "研报库", is_shared: false, doc_count: 1 },
    { id: "k2", name: "快讯库", is_shared: false, doc_count: 0 },
  ]),
  createKb: vi.fn(async (name: string) => ({
    id: "k9", name, is_shared: false, doc_count: 0,
  })),
  addKbItems: vi.fn(async () => ({ added: 1, duplicate: 0, failed: [] })),
  addKbSource: vi.fn(async () => ({
    id: "s1", source_type: "wechat_account", source_ref_id: "acc-1", display_name: "财经号",
    status: "pending", enabled: true, error: null, last_synced_at: null,
  })),
}));

function renderDialog(props: Record<string, unknown> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return import("./AddToKbDialog").then(({ default: AddToKbDialog }) =>
    render(
      <QueryClientProvider client={qc}>
        <AddToKbDialog
          open
          onClose={() => {}}
          mode="items"
          items={[{ source_type: "news_item", source_ref_id: "n1" }]}
          {...props}
        />
      </QueryClientProvider>,
    ),
  );
}

describe("AddToKbDialog", () => {
  afterEach(() => vi.clearAllMocks());

  it("列出用户的知识库", async () => {
    await renderDialog();
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    expect(screen.getByText("快讯库")).toBeTruthy();
  });

  it("选库后加入内容并提示结果", async () => {
    const kb = await import("@/lib/kb");
    await renderDialog();
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    fireEvent.click(screen.getByText("研报库"));
    await waitFor(() =>
      expect(kb.addKbItems).toHaveBeenCalledWith("k1", [
        { source_type: "news_item", source_ref_id: "n1" },
      ]),
    );
    await waitFor(() => expect(screen.getByText(/1 条已加入/)).toBeTruthy());
  });

  it("已在库中时给出明确提示而不是报错", async () => {
    const kb = await import("@/lib/kb");
    vi.mocked(kb.addKbItems).mockResolvedValue({ added: 0, duplicate: 1, failed: [] });
    await renderDialog();
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    fireEvent.click(screen.getByText("研报库"));
    await waitFor(() => expect(screen.getByText(/1 条已在库中/)).toBeTruthy());
  });

  it("部分失败时同时报出成功与失败条数", async () => {
    const kb = await import("@/lib/kb");
    vi.mocked(kb.addKbItems).mockResolvedValue({
      added: 2, duplicate: 1, failed: [{ source_ref_id: "x", error: "快讯不存在" }],
    });
    await renderDialog({
      items: [
        { source_type: "news_item", source_ref_id: "a" },
        { source_type: "news_item", source_ref_id: "b" },
        { source_type: "news_item", source_ref_id: "c" },
        { source_type: "news_item", source_ref_id: "x" },
      ],
    });
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    fireEvent.click(screen.getByText("研报库"));
    await waitFor(() => expect(screen.getByText(/2 条已加入/)).toBeTruthy());
    expect(screen.getByText(/1 条已在库中/)).toBeTruthy();
    expect(screen.getByText(/1 条失败/)).toBeTruthy();
  });

  it("新建并加入：先建库再加入新库", async () => {
    const kb = await import("@/lib/kb");
    await renderDialog();
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText("新建知识库并加入"), {
      target: { value: "新库" },
    });
    fireEvent.click(screen.getByTestId("add-to-kb-create"));
    await waitFor(() => expect(kb.createKb).toHaveBeenCalledWith("新库"));
    await waitFor(() => expect(kb.addKbItems).toHaveBeenCalledWith("k9", expect.anything()));
  });

  it("mode=source 时走整号订阅接口", async () => {
    const kb = await import("@/lib/kb");
    await renderDialog({
      mode: "source",
      items: undefined,
      source: { source_type: "wechat_account", source_ref_id: "acc-1", display_name: "财经号" },
    });
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    fireEvent.click(screen.getByText("研报库"));
    await waitFor(() =>
      expect(kb.addKbSource).toHaveBeenCalledWith("k1", {
        source_type: "wechat_account", source_ref_id: "acc-1", display_name: "财经号",
      }),
    );
    await waitFor(() => expect(screen.getByText(/已开始同步/)).toBeTruthy());
  });

  it("配额触顶等失败原样展示后端文案", async () => {
    const kb = await import("@/lib/kb");
    vi.mocked(kb.addKbItems).mockRejectedValue(new Error("该知识库已达 2000 篇文档上限"));
    await renderDialog();
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    fireEvent.click(screen.getByText("研报库"));
    await waitFor(() => expect(screen.getByText(/2000 篇文档上限/)).toBeTruthy());
  });

  it("open=false 时不渲染", async () => {
    await renderDialog({ open: false });
    expect(screen.queryByText("研报库")).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/AddToKbDialog.test.tsx`
Expected: FAIL — 找不到 `./AddToKbDialog`

- [ ] **Step 3: 实现 AddToKbDialog**

创建 `frontend/src/components/AddToKbDialog.tsx`：

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { addKbItems, addKbSource, createKb, fetchKbs } from "@/lib/kb";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Item = { source_type: string; source_ref_id: string };
type Source = { source_type: string; source_ref_id: string; display_name: string };

// 四处复用：公众号文章卡片、正文区、左侧订阅项（整号）、快讯多选操作行。
export default function AddToKbDialog({
  open,
  onClose,
  mode,
  items,
  source,
  title,
}: {
  open: boolean;
  onClose: () => void;
  mode: "items" | "source";
  items?: Item[];
  source?: Source;
  title?: string;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const { data: kbs = [], isLoading } = useQuery({
    queryKey: ["kb"],
    queryFn: fetchKbs,
    enabled: open,
  });

  const submit = useMutation({
    mutationFn: async (kbId: string) => {
      if (mode === "source") {
        if (!source) throw new Error("缺少订阅源信息");
        await addKbSource(kbId, source);
        return "已开始同步该号的历史文章，之后有新文章会自动入库";
      }
      const r = await addKbItems(kbId, items ?? []);
      const parts: string[] = [];
      if (r.added) parts.push(`${r.added} 条已加入`);
      if (r.duplicate) parts.push(`${r.duplicate} 条已在库中`);
      if (r.failed.length) parts.push(`${r.failed.length} 条失败`);
      return parts.join("，") || "没有可加入的内容";
    },
    onSuccess: (text) => {
      setMsg(text);
      qc.invalidateQueries({ queryKey: ["kb"] });
    },
    onError: (e) => setMsg(String(e instanceof Error ? e.message : e)),
  });

  const createAndAdd = useMutation({
    mutationFn: async () => {
      const kb = await createKb(name.trim());
      setName("");
      return kb.id;
    },
    onSuccess: (kbId) => {
      qc.invalidateQueries({ queryKey: ["kb"] });
      submit.mutate(kbId);
    },
    onError: (e) => setMsg(String(e instanceof Error ? e.message : e)),
  });

  if (!open) return null;

  const heading = title ?? (mode === "source" ? "整号订阅到知识库" : "加入知识库");
  const busy = submit.isPending || createAndAdd.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label={heading}
        className="w-80 rounded-lg border bg-background p-4 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">{heading}</h3>
          <button type="button" onClick={onClose} aria-label="关闭" className="text-muted-foreground hover:text-foreground">
            <X className="size-4" />
          </button>
        </div>

        <div className="mt-3 max-h-56 space-y-0.5 overflow-y-auto">
          {isLoading && <p className="text-xs text-muted-foreground">加载中…</p>}
          {!isLoading && kbs.length === 0 && (
            <p className="text-xs text-muted-foreground">还没有知识库，用下面的输入框建一个</p>
          )}
          {kbs.map((kb) => (
            <button
              key={kb.id}
              type="button"
              data-testid={`add-to-kb-${kb.id}`}
              disabled={busy}
              onClick={() => submit.mutate(kb.id)}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent/50 disabled:opacity-50"
            >
              <span className="min-w-0 flex-1 truncate">{kb.name}</span>
              <span className="shrink-0 text-xs text-muted-foreground">{kb.doc_count}</span>
            </button>
          ))}
        </div>

        <div className="mt-3 flex gap-1.5 border-t pt-3">
          <Input
            placeholder="新建知识库并加入"
            className="h-8 text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && name.trim()) createAndAdd.mutate();
            }}
          />
          <Button
            size="sm"
            data-testid="add-to-kb-create"
            disabled={!name.trim() || busy}
            onClick={() => createAndAdd.mutate()}
          >
            新建
          </Button>
        </div>

        {msg && <p className="mt-2 text-xs text-muted-foreground">{msg}</p>}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/components/AddToKbDialog.test.tsx`
Expected: PASS（8 个用例）

- [ ] **Step 5: 接入 SocialPanel 三处**

`frontend/src/panels/SocialPanel.tsx`——`WechatTab` 组件内加状态：

```tsx
  const [addTarget, setAddTarget] = useState<
    | { mode: "items"; items: { source_type: string; source_ref_id: string }[] }
    | { mode: "source"; source: { source_type: string; source_ref_id: string; display_name: string } }
    | null
  >(null);
```

顶部 import 补：

```tsx
import { Library } from "lucide-react";
import AddToKbDialog from "@/components/AddToKbDialog";
```

**接入点 1（文章卡片）**：文章列表里每个 `<li>`/卡片加 hover 出现的图标按钮：

```tsx
              <button
                type="button"
                data-testid={`social-add-kb-${a.id}`}
                aria-label="加入知识库"
                title="加入知识库"
                onClick={(e) => {
                  e.stopPropagation();
                  setAddTarget({
                    mode: "items",
                    items: [{ source_type: "wechat_article", source_ref_id: a.id }],
                  });
                }}
                className="shrink-0 text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100"
              >
                <Library className="size-3.5" />
              </button>
```

承载该按钮的元素需带 `group` class 才能触发 `group-hover`。

**接入点 2（正文区顶部）**：`reading` 分支里「原文链接」旁加：

```tsx
                  <button
                    type="button"
                    data-testid="social-add-kb-reading"
                    onClick={() =>
                      setAddTarget({
                        mode: "items",
                        items: [{ source_type: "wechat_article", source_ref_id: reading.id }],
                      })
                    }
                    className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                  >
                    <Library className="size-3.5" />
                    加入知识库
                  </button>
```

**接入点 3（左侧订阅项，整号）**：订阅列表每项加：

```tsx
              <button
                type="button"
                data-testid={`social-add-kb-account-${s.account_id}`}
                aria-label="整号加入知识库"
                title="整号加入知识库"
                onClick={(e) => {
                  e.stopPropagation();
                  setAddTarget({
                    mode: "source",
                    source: {
                      source_type: "wechat_account",
                      source_ref_id: s.account_id,
                      display_name: s.name,
                    },
                  });
                }}
                className="shrink-0 text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100"
              >
                <Library className="size-3.5" />
              </button>
```

组件 return 的最外层末尾挂弹窗：

```tsx
      {addTarget && (
        <AddToKbDialog
          open
          onClose={() => setAddTarget(null)}
          mode={addTarget.mode}
          items={addTarget.mode === "items" ? addTarget.items : undefined}
          source={addTarget.mode === "source" ? addTarget.source : undefined}
        />
      )}
```

`AddToKbDialog` 用了 TanStack Query，而 `SocialPanel` 目前是纯 `useState`/`useEffect`。`ChatPage` 上层已有 `QueryClientProvider`（`KbPanel` 依赖它），所以这里能直接用；若 `SocialPanel.test.tsx` 因此报 "No QueryClient set"，在该测试文件的 render 外层补一个 `QueryClientProvider` 即可。

- [ ] **Step 6: 接入 NewsAssistant 批量加入**

`frontend/src/panels/NewsAssistant.tsx`——`NewsAssistantInner` 内加状态与 import：

```tsx
import { Library } from "lucide-react";
import AddToKbDialog from "@/components/AddToKbDialog";
```

```tsx
  const [addOpen, setAddOpen] = useState(false);
```

「已选 N/5 条」那一行（`selectedItems.length > 0` 分支）里，在「时间线」按钮之后插入：

```tsx
            <button
              type="button"
              data-testid="news-add-kb"
              onClick={() => setAddOpen(true)}
              className="flex items-center gap-0.5 rounded-md border border-border px-2 py-0.5 text-xs hover:bg-accent"
            >
              <Library className="size-3" />
              加入知识库
            </button>
```

组件 return 末尾（最外层 `</div>` 之前）挂：

```tsx
      {addOpen && (
        <AddToKbDialog
          open
          onClose={() => setAddOpen(false)}
          mode="items"
          items={selectedItems.map((i) => ({ source_type: "news_item", source_ref_id: i.id }))}
        />
      )}
```

- [ ] **Step 7: 跑全部前端测试**

Run: `cd frontend && npx vitest run && npx tsc -b && npm run lint`
Expected: 全 PASS

- [ ] **Step 8: 提交**

```bash
cd frontend
git add src/components/AddToKbDialog.tsx src/components/AddToKbDialog.test.tsx \
        src/panels/SocialPanel.tsx src/panels/NewsAssistant.tsx
git commit -m "feat(kb): 加入知识库弹窗与四处接入点"
```

---

## Task 13: 端到端验证

**Files:**
- Test: `backend/tests/test_kb_content_flow.py`

**Interfaces:**
- Consumes: 前面所有任务

- [ ] **Step 1: 写闭环测试**

创建 `backend/tests/test_kb_content_flow.py`：

```python
import asyncio
import datetime as dt
import uuid

import pytest

from app.kb.retrieval import search_chunks
from tests.conftest import _auth


@pytest.fixture
def fast_limiter(monkeypatch):
    from app.core import config
    from app.kb.ratelimit import reset_for_tests

    monkeypatch.setenv("KB_BACKFILL_DELAY_SECONDS", "0")
    config.get_settings.cache_clear()
    reset_for_tests()
    yield
    config.get_settings.cache_clear()
    reset_for_tests()


@pytest.mark.asyncio
async def test_wechat_article_to_retrieval(client, db_session, registered_user, fast_limiter):
    """闭环：公众号文章 → 加入知识库 → 后台切片 → kb_search 能检索到且带出处。"""
    from app.social.ingest import get_or_create_account
    from app.social.models import WechatArticle

    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "社媒库"}, headers=h)).json()["id"]

    acc = await get_or_create_account(db_session, f"F{uuid.uuid4().hex[:8]}", "财经号")
    art = WechatArticle(
        account_id=acc.id, external_id=f"a{uuid.uuid4().hex[:8]}", title="茅台年报解读",
        digest="", cover_url=None, url="https://mp.weixin.qq.com/s/flow",
        content="贵州茅台2025年净利润同比增长，毛利率维持高位。" * 10,
        published_at=dt.datetime(2026, 7, 15, tzinfo=dt.UTC),
    )
    db_session.add(art)
    await db_session.commit()

    r = (await client.post(f"/api/kb/{kb_id}/items", headers=h, json={
        "items": [{"source_type": "wechat_article", "source_ref_id": str(art.id)}]})).json()
    assert r["added"] == 1

    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if docs and docs[0]["status"] in ("ready", "failed"):
            break
        await asyncio.sleep(0.1)
    assert docs[0]["status"] == "ready", docs[0].get("error")

    hits = await search_chunks(db_session, [uuid.UUID(kb_id)], "茅台 净利润")
    assert hits
    # 出处用 title——社媒文档没有 filename
    assert hits[0]["filename"] == "茅台年报解读"


@pytest.mark.asyncio
async def test_news_item_to_retrieval(client, db_session, registered_user, fast_limiter):
    from app.news.models import NewsItem, NewsSource

    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "快讯库"}, headers=h)).json()["id"]

    src = NewsSource(name="新浪", type="sina_live", channel="news", config={})
    db_session.add(src)
    await db_session.flush()
    item = NewsItem(source_id=src.id, channel="news", external_id=f"n{uuid.uuid4().hex[:8]}",
                    content_hash=uuid.uuid4().hex, title="央行宣布降准",
                    content="央行决定于下月起下调存款准备金率0.5个百分点。" * 8,
                    url="https://finance.sina.com.cn/flow",
                    published_at=dt.datetime(2026, 7, 16, tzinfo=dt.UTC))
    db_session.add(item)
    await db_session.commit()

    await client.post(f"/api/kb/{kb_id}/items", headers=h, json={
        "items": [{"source_type": "news_item", "source_ref_id": str(item.id)}]})
    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if docs and docs[0]["status"] in ("ready", "failed"):
            break
        await asyncio.sleep(0.1)
    assert docs[0]["status"] == "ready"

    hits = await search_chunks(db_session, [uuid.UUID(kb_id)], "降准 存款准备金率")
    assert hits and hits[0]["filename"] == "央行宣布降准"


@pytest.mark.asyncio
async def test_upload_path_still_works(client, registered_user):
    """回归：重构 ingest 后上传路径行为不变，出处仍是文件名。"""
    import io

    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "上传回归"}, headers=h)).json()["id"]
    files = {"file": ("maotai.txt", io.BytesIO("贵州茅台净利润大幅增长。".encode("utf-8")),
                      "text/plain")}
    assert (await client.post(f"/api/kb/{kb_id}/documents", files=files,
                              headers=h)).status_code == 200
    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if docs and docs[0]["status"] in ("ready", "failed"):
            break
        await asyncio.sleep(0.1)
    assert docs[0]["status"] == "ready"
    assert docs[0]["filename"] == "maotai.txt" and docs[0]["title"] == "maotai.txt"
    assert docs[0]["source_type"] == "upload"
```

- [ ] **Step 2: 让检索出处兼容无 filename 的文档**

`search_chunks` 返回的 `filename` 直接取 `KbDocument.filename`，社媒/快讯文档该列为 NULL，`kb_search` 工具会输出「出处：None」。

`backend/app/kb/retrieval.py` 的 `search_chunks` 改为选 `title`：

```python
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
```

- [ ] **Step 3: 跑闭环测试**

Run: `cd backend && uv run pytest tests/test_kb_content_flow.py -v`
Expected: PASS（3 个用例）

- [ ] **Step 4: 全量回归**

Run: `cd backend && uv run pytest -q && uv run ruff check app tests`
Expected: 全 PASS

Run: `cd frontend && npx vitest run && npx tsc -b && npm run lint`
Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
cd backend
git add app/kb/retrieval.py tests/test_kb_content_flow.py
git commit -m "test(kb): 内容源入库到检索的端到端闭环；出处改用 title"
```

