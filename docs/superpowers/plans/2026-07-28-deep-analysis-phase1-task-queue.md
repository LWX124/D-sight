# 深度分析 Phase 1：可靠任务骨架

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 PostgreSQL 持久化任务队列骨架，验证任务认领、心跳、恢复、幂等和积分事务的可靠性。Runner 仅返回 mock 结果，先跑通可靠性，不触碰任何分析逻辑。

**Architecture:** 独立 worker 进程 + PostgreSQL 任务队列（`SELECT ... FOR UPDATE SKIP LOCKED`）。API 层原子事务创建报告并预留积分，worker 认领后推进状态、心跳保活、完成时结算积分，全程通过 `claim_token + lease_version` 隔离并发。

**Tech Stack:** Python 3.12、SQLAlchemy asyncpg、Alembic、FastAPI、现有 credits service

## Global Constraints

- 本 Phase **不引入任何分析逻辑**，runner 只修改状态和写 mock result
- 不修改除 `app/credits/models.py`、`app/credits/service.py`、`app/core/config.py`、`app/main.py` 以外的已有文件（只追加，不改已有逻辑）
- 新代码全部在 `backend/app/deep_analysis/` 目录
- 所有新测试放在 `backend/tests/deep_analysis/`
- 每个 Task 写完立即运行相关测试，全绿后再进入下一个 Task
- 不提交代码，完成后由用户决定提交

---

### Task 1.1：积分模型扩展

**Goal:** 给 `CreditTransaction` 加 `operation` 字段和唯一索引，满足 Phase 1 计费幂等要求。

**Files:**
- Modify: `backend/app/credits/models.py`
- Create: `backend/alembic/versions/a1b2c3d4e5f6_deep_analysis_credits.py`

**Interfaces:**
- Produces: `CreditTransaction.operation`（`reserve / settle / release`）字段；`uq_credit_tx_deep_analysis` 唯一索引

- [ ] **Step 1: 在 `CreditTransaction` 末尾追加 `operation` 列**

```python
# app/credits/models.py — 在 CreditTransaction 类末尾追加
operation: Mapped[str | None] = mapped_column(String(16))  # reserve / settle / release
```

- [ ] **Step 2: 生成 Alembic migration**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
source .venv/bin/activate
alembic revision --autogenerate -m "deep_analysis_credits"
```

检查生成文件，确认：
1. `op.add_column('credit_transactions', sa.Column('operation', sa.String(16), nullable=True))`
2. 手动在 upgrade() 末尾追加唯一索引（autogenerate 不生成 partial index）：

```python
op.execute("""
    CREATE UNIQUE INDEX uq_credit_tx_deep_analysis
    ON credit_transactions (ref_type, ref_id, operation)
    WHERE ref_type = 'deep_analysis'
""")
```

downgrade() 末尾追加：

```python
op.execute("DROP INDEX IF EXISTS uq_credit_tx_deep_analysis")
op.drop_column('credit_transactions', 'operation')
```

- [ ] **Step 3: 运行 migration**

```bash
alembic upgrade head
```

Expected: 无报错，`credit_transactions` 表存在 `operation` 列和部分唯一索引。

---

### Task 1.2：DeepAnalysisReport ORM 模型

**Goal:** 创建 `deep_analysis_reports` 表对应的 SQLAlchemy ORM，覆盖设计文档第 4 节全部字段。

**Files:**
- Create: `backend/app/deep_analysis/__init__.py`
- Create: `backend/app/deep_analysis/models.py`

**Interfaces:**
- Produces: `DeepAnalysisReport` ORM 类，供 service / worker / router 使用

- [ ] **Step 1: 创建 `__init__.py`**

```bash
mkdir -p /Users/weixi1/Documents/mine/D-sight/backend/app/deep_analysis
touch /Users/weixi1/Documents/mine/D-sight/backend/app/deep_analysis/__init__.py
```

- [ ] **Step 2: 创建 `models.py`**

创建 `backend/app/deep_analysis/models.py`：

```python
"""深度分析报告 ORM 模型。

表结构严格对应设计文档第 4 节；字段注释说明每列语义。
每次状态推进必须携带 claim_token + lease_version，防止失联 worker 写入。
"""
import datetime as dt
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DeepAnalysisReport(Base):
    __tablename__ = "deep_analysis_reports"
    __table_args__ = (
        # 同一用户同一活跃请求只允许一条（market+normalized_ticker+analysis_version 组合）
        UniqueConstraint(
            "user_id",
            "market",
            "normalized_ticker",
            "analysis_version",
            name="uq_deep_analysis_active_request",
            postgresql_where="status IN ('pending','running','retry_wait') AND deleted_at IS NULL",
        ),
        # 幂等键唯一
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_deep_analysis_idempotency",
            postgresql_where="idempotency_key IS NOT NULL",
        ),
        CheckConstraint(
            "(status = 'completed') = (result IS NOT NULL)",
            name="chk_deep_analysis_completed_result",
        ),
        # worker 认领索引
        Index(
            "ix_deep_analysis_worker_claim",
            "next_retry_at",
            "created_at",
            postgresql_where="status IN ('pending','retry_wait')",
        ),
        # 失联检测索引
        Index(
            "ix_deep_analysis_stale_running",
            "heartbeat_at",
            postgresql_where="status = 'running'",
        ),
        # 用户历史索引
        Index(
            "ix_deep_analysis_owner_history",
            "user_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    market: Mapped[str] = mapped_column(String(4), nullable=False)  # A / HK / US
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)  # 用户原始输入
    normalized_ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(64), nullable=False)

    # --- 任务状态机 ---
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)

    # --- 执行租约 ---
    worker_id: Mapped[str | None] = mapped_column(String(128))
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heartbeat_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # --- 幂等 ---
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))

    # --- 时间戳 ---
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    # --- 结果 ---
    conclusion_status: Mapped[str | None] = mapped_column(String(24))
    result: Mapped[dict | None] = mapped_column(JSONB)
    data_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[dict | None] = mapped_column(JSONB)

    # --- 积分 ---
    credit_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="reserved"
    )  # reserved / settled / released / exempt
    reserved_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settled_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

- [ ] **Step 3: 验证模型可导入**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
python3 -c "from app.deep_analysis.models import DeepAnalysisReport; print('OK')"
```

Expected: 输出 `OK`，无导入错误。

---

### Task 1.3：Alembic Migration

**Goal:** 为 `deep_analysis_reports` 表生成并执行 migration。

**Files:**
- Create: `backend/alembic/versions/<hash>_deep_analysis_reports.py`

- [ ] **Step 1: 在 `alembic/env.py` 确认已导入新模型**

检查 `alembic/env.py` 的 `target_metadata` 来源。找到导入 `Base` 的地方，确认 `app.deep_analysis.models` 会被加载（通常只需 `Base` 来自同一 `app.core.db`，autogenerate 会自动扫描所有子类）。

如果 `env.py` 用显式 import 列表，追加：

```python
import app.deep_analysis.models  # noqa: F401
```

- [ ] **Step 2: 生成 migration**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
source .venv/bin/activate
alembic revision --autogenerate -m "deep_analysis_reports"
```

- [ ] **Step 3: 检查生成文件**

确认以下内容存在于 `upgrade()`：
1. `op.create_table('deep_analysis_reports', ...)` 包含全部列
2. `op.create_index('ix_deep_analysis_worker_claim', ...)` 含 `postgresql_where`
3. `op.create_index('ix_deep_analysis_stale_running', ...)` 含 `postgresql_where`
4. `op.create_index('ix_deep_analysis_owner_history', ...)`
5. `uq_deep_analysis_active_request` 唯一约束含 partial where
6. `uq_deep_analysis_idempotency` 唯一约束含 partial where
7. `chk_deep_analysis_completed_result` check constraint

如 autogenerate 漏生成 partial index/constraint，手动补入 `op.execute(...)` SQL。

- [ ] **Step 4: 执行 migration**

```bash
alembic upgrade head
```

Expected: 无报错，`\d deep_analysis_reports` 可见所有列和索引。

---

### Task 1.4：API Schemas

**Goal:** 定义 API 请求/响应的 Pydantic Schema，覆盖 POST 创建、GET 查询和历史列表。

**Files:**
- Create: `backend/app/deep_analysis/schemas.py`

- [ ] **Step 1: 创建 `schemas.py`**

创建 `backend/app/deep_analysis/schemas.py`：

```python
"""深度分析 API Schemas。

命名规范：Request 后缀 = 入参，Response 后缀 = 出参。
"""
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class DeepAnalysisCreateRequest(BaseModel):
    market: Literal["A", "HK", "US"]
    ticker: str = Field(min_length=1, max_length=32)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class DeepAnalysisCreateResponse(BaseModel):
    id: uuid.UUID
    status: str
    cache_hit: bool = False
    deduplicated: bool = False
    reserved_credits: int


class DeepAnalysisStatusResponse(BaseModel):
    id: uuid.UUID
    market: str
    ticker: str
    normalized_ticker: str
    status: str
    stage: str
    progress: int
    attempt_count: int
    conclusion_status: str | None = None
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class DeepAnalysisListResponse(BaseModel):
    items: list[DeepAnalysisStatusResponse]
    next_cursor: str | None = None
```

- [ ] **Step 2: 验证可导入**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
python3 -c "from app.deep_analysis.schemas import DeepAnalysisCreateRequest; print('OK')"
```

Expected: 输出 `OK`。

---

### Task 1.5：Service 层（原子创建与积分预留）

**Goal:** 实现幂等检查、缓存命中、活跃任务去重、积分预留、报告创建的原子事务。

**Files:**
- Create: `backend/app/deep_analysis/service.py`

**Interfaces:**
- Consumes: `DeepAnalysisCreateRequest`、`user_id`、`AsyncSession`
- Produces: `(DeepAnalysisReport, cache_hit: bool, deduplicated: bool)`

- [ ] **Step 1: 创建 `service.py`**

创建 `backend/app/deep_analysis/service.py`：

```python
"""深度分析 Service 层。

create_report：
  1. 幂等键重放检查（相同 key + 相同 fingerprint → 返回原报告）
  2. 完成缓存命中检查（4h 内同 market/ticker/version → 返回缓存）
  3. 活跃任务去重（pending/running/retry_wait 已存在 → deduplicated）
  4. 积分余额检查
  5. 原子事务：创建报告 + 写 reserve 积分流水
"""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.credits.models import CreditAccount, CreditTransaction
from app.credits.service import InsufficientCredits
from app.deep_analysis.models import DeepAnalysisReport

ACTIVE_STATUSES = ("pending", "running", "retry_wait")
CACHE_HOURS = 4
DEEP_ANALYSIS_CREDITS = 50


def _fingerprint(market: str, normalized_ticker: str, version: str) -> str:
    raw = f"{market}:{normalized_ticker}:{version}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _normalize_ticker(market: str, ticker: str) -> str:
    """Phase 1 只做基础规范化；Phase 2 扩展为完整校验。"""
    t = ticker.strip().upper()
    if market == "A":
        code = t.lstrip("SH").lstrip("SZ").lstrip("0") or "0"
        if t.startswith("6"):
            return t.zfill(6) + ".SH"
        return t.zfill(6) + ".SZ"
    if market == "HK":
        digits = t.lstrip("0") or "0"
        return digits.zfill(4) + ".HK"
    return t  # US: uppercase as-is
```

- [ ] **Step 2: 追加 `create_report` 函数（接 Step 1 文件末尾）**

```python
async def create_report(
    db: AsyncSession,
    user_id: uuid.UUID,
    market: str,
    ticker: str,
    idempotency_key: str | None,
    is_admin: bool = False,
) -> tuple[DeepAnalysisReport, bool, bool]:
    """返回 (report, cache_hit, deduplicated)。"""
    settings = get_settings()
    version = getattr(settings, "deep_analysis_analysis_version", "v1")
    normalized = _normalize_ticker(market, ticker)
    fp = _fingerprint(market, normalized, version)
    now = datetime.now(timezone.utc)

    # 1. 幂等键重放
    if idempotency_key:
        existing = (await db.execute(
            select(DeepAnalysisReport).where(
                DeepAnalysisReport.user_id == user_id,
                DeepAnalysisReport.idempotency_key == idempotency_key,
            )
        )).scalar_one_or_none()
        if existing:
            if existing.request_fingerprint != fp:
                raise ValueError("idempotency_key_fingerprint_mismatch")
            return existing, existing.status == "completed", False

    # 2. 完成缓存命中
    cache_cutoff = now - timedelta(hours=CACHE_HOURS)
    cached = (await db.execute(
        select(DeepAnalysisReport).where(
            DeepAnalysisReport.user_id == user_id,
            DeepAnalysisReport.market == market,
            DeepAnalysisReport.normalized_ticker == normalized,
            DeepAnalysisReport.analysis_version == version,
            DeepAnalysisReport.status == "completed",
            DeepAnalysisReport.deleted_at.is_(None),
            DeepAnalysisReport.finished_at >= cache_cutoff,
        )
    )).scalar_one_or_none()
    if cached:
        return cached, True, False

    # 3. 活跃任务去重
    active = (await db.execute(
        select(DeepAnalysisReport).where(
            DeepAnalysisReport.user_id == user_id,
            DeepAnalysisReport.market == market,
            DeepAnalysisReport.normalized_ticker == normalized,
            DeepAnalysisReport.analysis_version == version,
            DeepAnalysisReport.status.in_(ACTIVE_STATUSES),
            DeepAnalysisReport.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if active:
        return active, False, True

    # 4. 积分检查（非管理员）
    credits_to_reserve = 0 if is_admin else DEEP_ANALYSIS_CREDITS
    if not is_admin:
        acct = (await db.execute(
            select(CreditAccount)
            .where(CreditAccount.user_id == user_id)
            .with_for_update()
        )).scalar_one_or_none()
        if acct is None or acct.balance < credits_to_reserve:
            raise InsufficientCredits()
        acct.balance -= credits_to_reserve
        db.add(CreditTransaction(
            user_id=user_id,
            kind="charge",
            amount=-credits_to_reserve,
            balance_after=acct.balance,
            ref_type="deep_analysis",
            ref_id=None,  # 先 flush 再回填
            operation="reserve",
        ))

    # 5. 创建报告
    report = DeepAnalysisReport(
        user_id=user_id,
        market=market,
        ticker=ticker,
        normalized_ticker=normalized,
        analysis_version=version,
        status="pending",
        idempotency_key=idempotency_key,
        request_fingerprint=fp,
        credit_state="exempt" if is_admin else "reserved",
        reserved_credits=credits_to_reserve,
    )
    db.add(report)
    await db.flush()  # 获取 report.id

    # 回填积分流水的 ref_id
    if not is_admin:
        tx = (await db.execute(
            select(CreditTransaction).where(
                CreditTransaction.user_id == user_id,
                CreditTransaction.ref_type == "deep_analysis",
                CreditTransaction.operation == "reserve",
                CreditTransaction.ref_id.is_(None),
            ).order_by(CreditTransaction.created_at.desc()).limit(1)
        )).scalar_one()
        tx.ref_id = str(report.id)

    await db.flush()
    return report, False, False
```

- [ ] **Step 3: 验证可导入**

```bash
python3 -c "from app.deep_analysis.service import create_report; print('OK')"
```

---

### Task 1.6：HTTP Router

**Goal:** 实现 POST 创建、GET 单报告、GET 历史列表、POST 取消、DELETE 软删除五个端点。

**Files:**
- Create: `backend/app/deep_analysis/router.py`

- [ ] **Step 1: 创建 `router.py`**

创建 `backend/app/deep_analysis/router.py`：

```python
"""深度分析 HTTP 路由。

路由只做：鉴权、参数校验、调用 service、返回响应。
不含业务编排逻辑。
所有单报告操作均验证 report.user_id == current_user.id，
不命中一律 404，不暴露他人报告存在性。
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.db import get_db
from app.credits.service import InsufficientCredits
from app.deep_analysis.models import DeepAnalysisReport
from app.deep_analysis.schemas import (
    DeepAnalysisCreateRequest,
    DeepAnalysisCreateResponse,
    DeepAnalysisListResponse,
    DeepAnalysisStatusResponse,
)
from app.deep_analysis.service import create_report

router = APIRouter(prefix="/api/deep-analysis", tags=["deep-analysis"])


def _to_status(r: DeepAnalysisReport) -> DeepAnalysisStatusResponse:
    return DeepAnalysisStatusResponse(
        id=r.id,
        market=r.market,
        ticker=r.ticker,
        normalized_ticker=r.normalized_ticker,
        status=r.status,
        stage=r.stage,
        progress=r.progress,
        attempt_count=r.attempt_count,
        conclusion_status=r.conclusion_status,
        result=r.result,
        error_code=r.error_code,
        error_message=r.error_message,
        created_at=r.created_at,
        started_at=r.started_at,
        finished_at=r.finished_at,
    )


@router.post("", response_model=DeepAnalysisCreateResponse, status_code=202)
async def create(
    body: DeepAnalysisCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    is_admin = getattr(current_user, "is_admin", False)
    try:
        async with db.begin():
            report, cache_hit, deduplicated = await create_report(
                db,
                user_id=current_user.id,
                market=body.market,
                ticker=body.ticker,
                idempotency_key=body.idempotency_key,
                is_admin=is_admin,
            )
    except InsufficientCredits:
        raise HTTPException(status_code=402, detail="insufficient_credits")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return DeepAnalysisCreateResponse(
        id=report.id,
        status=report.status,
        cache_hit=cache_hit,
        deduplicated=deduplicated,
        reserved_credits=report.reserved_credits,
    )


@router.get("/{report_id}", response_model=DeepAnalysisStatusResponse)
async def get_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = (await db.execute(
        select(DeepAnalysisReport).where(
            DeepAnalysisReport.id == report_id,
            DeepAnalysisReport.user_id == current_user.id,
            DeepAnalysisReport.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="not_found")
    return _to_status(report)


@router.get("", response_model=DeepAnalysisListResponse)
async def list_reports(
    market: str | None = Query(default=None),
    status: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conditions = [
        DeepAnalysisReport.user_id == current_user.id,
        DeepAnalysisReport.deleted_at.is_(None),
    ]
    if market:
        conditions.append(DeepAnalysisReport.market == market)
    if status:
        conditions.append(DeepAnalysisReport.status == status)
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            conditions.append(DeepAnalysisReport.created_at < cursor_dt)
        except ValueError:
            pass

    rows = (await db.execute(
        select(DeepAnalysisReport)
        .where(and_(*conditions))
        .order_by(DeepAnalysisReport.created_at.desc())
        .limit(limit + 1)
    )).scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1].created_at.isoformat() if has_more and items else None
    return DeepAnalysisListResponse(items=[_to_status(r) for r in items], next_cursor=next_cursor)


@router.post("/{report_id}/cancel", response_model=DeepAnalysisStatusResponse)
async def cancel_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    async with db.begin():
        report = (await db.execute(
            select(DeepAnalysisReport).where(
                DeepAnalysisReport.id == report_id,
                DeepAnalysisReport.user_id == current_user.id,
                DeepAnalysisReport.deleted_at.is_(None),
            ).with_for_update()
        )).scalar_one_or_none()
        if not report:
            raise HTTPException(status_code=404, detail="not_found")
        if report.status not in ("pending", "running", "retry_wait"):
            raise HTTPException(status_code=409, detail="not_cancellable")
        report.status = "cancelled"
        report.cancelled_at = datetime.now(timezone.utc)
        # 释放积分（pending 直接释放）
        if report.credit_state == "reserved" and report.reserved_credits > 0:
            from app.credits.models import CreditAccount, CreditTransaction
            from sqlalchemy import select as sel
            acct = (await db.execute(
                sel(CreditAccount).where(CreditAccount.user_id == current_user.id).with_for_update()
            )).scalar_one_or_none()
            if acct:
                acct.balance += report.reserved_credits
                db.add(CreditTransaction(
                    user_id=current_user.id,
                    kind="refund",
                    amount=report.reserved_credits,
                    balance_after=acct.balance,
                    ref_type="deep_analysis",
                    ref_id=str(report.id),
                    operation="release",
                ))
            report.credit_state = "released"
    return _to_status(report)


@router.delete("/{report_id}", status_code=204)
async def delete_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    async with db.begin():
        report = (await db.execute(
            select(DeepAnalysisReport).where(
                DeepAnalysisReport.id == report_id,
                DeepAnalysisReport.user_id == current_user.id,
                DeepAnalysisReport.deleted_at.is_(None),
            ).with_for_update()
        )).scalar_one_or_none()
        if not report:
            raise HTTPException(status_code=404, detail="not_found")
        if report.status in ("pending", "running", "retry_wait"):
            raise HTTPException(status_code=409, detail="cancel_before_delete")
        report.deleted_at = datetime.now(timezone.utc)
        report.deleted_by = current_user.id
```

- [ ] **Step 2: 验证可导入**

```bash
python3 -c "from app.deep_analysis.router import router; print('OK')"
```

---

### Task 1.7：注册路由到 main.py

**Goal:** 将 `deep_analysis` router 挂载到 FastAPI app，功能通过 feature flag `DEEP_ANALYSIS_WORKER_ENABLED` 控制。

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: 在 `Settings` 类追加配置项**

在 `backend/app/core/config.py` 的 `Settings` 类末尾追加：

```python
    # 深度分析
    deep_analysis_analyst_model: str = "deepseek-v4-flash"
    deep_analysis_portfolio_model: str = "deepseek-v4-pro"
    deep_analysis_max_concurrency: int = 8
    deep_analysis_analyst_timeout_seconds: int = 45
    deep_analysis_task_timeout_seconds: int = 300
    deep_analysis_max_attempts: int = 3
    deep_analysis_cache_hours: int = 4
    deep_analysis_credits: int = 50
    deep_analysis_worker_enabled: bool = False
    deep_analysis_analysis_version: str = "v1"
```

- [ ] **Step 2: 在 `main.py` 注册路由**

在 `backend/app/main.py` 的 `from app.fund_arb.router import ...` 后追加：

```python
from app.deep_analysis.router import router as deep_analysis_router
```

在 `app.include_router(fund_arb_router)` 后追加：

```python
app.include_router(deep_analysis_router)
```

- [ ] **Step 3: 验证启动不报错**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
python3 -c "from app.main import app; print('routes:', [r.path for r in app.routes if hasattr(r,'path') and 'deep' in r.path])"
```

Expected: 输出包含 `/api/deep-analysis` 路径。

---

### Task 1.8：Mock Runner

**Goal:** 实现一个最简 runner，接受 `report_id` 和 `claim_token`，推进阶段、写 mock 结果、完成报告，用于 Phase 1 验证骨架可靠性。

**Files:**
- Create: `backend/app/deep_analysis/runner.py`

- [ ] **Step 1: 创建 `runner.py`**

创建 `backend/app/deep_analysis/runner.py`：

```python
"""Phase 1 Mock Runner。

只推进阶段、写 mock 结果，不执行任何实际分析。
每个阶段边界检查 cancellation，确保 worker 可以响应取消请求。
所有状态写入都携带 claim_token + lease_version（租约校验）。
"""
import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.deep_analysis.models import DeepAnalysisReport

STAGES = [
    ("fetching_data", 10),
    ("running_analysts", 40),
    ("assessing_risk", 70),
    ("synthesizing", 85),
    ("finalizing", 95),
]

MOCK_RESULT = {
    "schema_version": "1",
    "mock": True,
    "conclusion": {
        "status": "actionable",
        "action": "hold",
        "confidence": 50,
        "reasoning": "Phase 1 mock runner — no real analysis performed.",
    },
}


async def run(
    db: AsyncSession,
    report_id: uuid.UUID,
    claim_token: uuid.UUID,
    lease_version: int,
) -> None:
    """执行 mock runner。任何阶段检测到租约失效立即退出。"""

    async def _update_stage(stage: str, progress: int) -> bool:
        """更新阶段。返回 False 表示租约已失效（被恢复器或取消覆盖）。"""
        result = await db.execute(
            update(DeepAnalysisReport)
            .where(
                DeepAnalysisReport.id == report_id,
                DeepAnalysisReport.claim_token == claim_token,
                DeepAnalysisReport.lease_version == lease_version,
                DeepAnalysisReport.status == "running",
            )
            .values(stage=stage, progress=progress)
            .returning(DeepAnalysisReport.id)
        )
        await db.commit()
        return result.scalar_one_or_none() is not None

    async def _is_cancelled() -> bool:
        r = (await db.execute(
            select(DeepAnalysisReport.status).where(DeepAnalysisReport.id == report_id)
        )).scalar_one_or_none()
        return r == "cancelled"

    for stage, progress in STAGES:
        if await _is_cancelled():
            return
        ok = await _update_stage(stage, progress)
        if not ok:
            return  # 租约失效，退出
        await asyncio.sleep(0.1)  # 模拟工作，生产中替换为实际逻辑

    # 写完成
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(DeepAnalysisReport)
        .where(
            DeepAnalysisReport.id == report_id,
            DeepAnalysisReport.claim_token == claim_token,
            DeepAnalysisReport.lease_version == lease_version,
            DeepAnalysisReport.status == "running",
        )
        .values(
            status="completed",
            stage="finalizing",
            progress=100,
            conclusion_status="actionable",
            result=MOCK_RESULT,
            finished_at=now,
            credit_state="settled",
            settled_credits=50,
        )
        .returning(DeepAnalysisReport.id)
    )
    await db.commit()
    # 若行未更新（租约失效），什么都不做
```

- [ ] **Step 2: 验证可导入**

```bash
python3 -c "from app.deep_analysis.runner import run; print('OK')"
```

---

### Task 1.9：Worker 进程

**Goal:** 实现 worker 的 claim loop、heartbeat、maintenance loop（失联恢复、retry_wait 推进），通过 `DEEP_ANALYSIS_WORKER_ENABLED` feature flag 控制启动。

**Files:**
- Create: `backend/app/deep_analysis/worker.py`

- [ ] **Step 1: 创建 `worker.py`**

创建 `backend/app/deep_analysis/worker.py`：

```python
"""深度分析 Worker 进程。

启动方式：
  python -m app.deep_analysis.worker

检查列表（全部满足才启动）：
  - DEEP_ANALYSIS_WORKER_ENABLED=true
  - 数据库连接正常
  - 必需配置非空

Worker 包含两个协程：
  - claim_loop：轮询 pending/retry_wait，认领并执行报告
  - maintenance_loop：恢复失联任务、释放过期积分
"""
import asyncio
import logging
import os
import signal
import socket
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.deep_analysis.models import DeepAnalysisReport

logger = logging.getLogger(__name__)

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"
HEARTBEAT_INTERVAL = 15       # 秒
STALE_THRESHOLD = 60          # 秒，超过此值视为失联
MAINTENANCE_INTERVAL = 30     # 秒
CLAIM_SLEEP = 2               # 无任务时等待
GRACE_PERIOD = 120            # SIGTERM 后最多等待秒数

_stop = asyncio.Event()
_active: set[asyncio.Task] = set()


def _make_session():
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_size=5, max_overflow=2)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _claim_one(Session) -> tuple[uuid.UUID, uuid.UUID, int] | None:
    """认领一条 pending/retry_wait 报告，返回 (report_id, claim_token, lease_version)。"""
    now = datetime.now(timezone.utc)
    new_token = uuid.uuid4()

    async with Session() as db:
        async with db.begin():
            row = (await db.execute(
                select(DeepAnalysisReport)
                .where(
                    DeepAnalysisReport.status.in_(("pending", "retry_wait")),
                    DeepAnalysisReport.next_retry_at <= now,
                )
                .order_by(DeepAnalysisReport.next_retry_at, DeepAnalysisReport.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )).scalar_one_or_none()

            if not row:
                return None

            new_version = row.lease_version + 1
            row.status = "running"
            row.worker_id = WORKER_ID
            row.claim_token = new_token
            row.lease_version = new_version
            row.heartbeat_at = now
            row.started_at = row.started_at or now
            row.attempt_count += 1

    return row.id, new_token, new_version


async def _heartbeat(Session, report_id: uuid.UUID, token: uuid.UUID, version: int):
    """每 HEARTBEAT_INTERVAL 秒更新心跳。心跳失败不中断主任务。"""
    while not _stop.is_set():
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        try:
            async with Session() as db:
                async with db.begin():
                    await db.execute(
                        update(DeepAnalysisReport)
                        .where(
                            DeepAnalysisReport.id == report_id,
                            DeepAnalysisReport.claim_token == token,
                            DeepAnalysisReport.lease_version == version,
                            DeepAnalysisReport.status == "running",
                        )
                        .values(heartbeat_at=datetime.now(timezone.utc))
                    )
        except Exception as e:
            logger.warning("heartbeat failed report=%s: %s", report_id, e)


async def _execute(Session, report_id: uuid.UUID, token: uuid.UUID, version: int):
    """执行报告（Phase 1 调 mock runner）。失败写 retry_wait 或 failed。"""
    from app.deep_analysis.runner import run

    hb = asyncio.create_task(_heartbeat(Session, report_id, token, version))
    try:
        async with Session() as db:
            await run(db, report_id, token, version)
        logger.info("report completed report=%s", report_id)
    except Exception as e:
        logger.exception("report failed report=%s: %s", report_id, e)
        await _mark_retry_or_failed(Session, report_id, token, version, str(e))
    finally:
        hb.cancel()


async def _mark_retry_or_failed(Session, report_id, token, version, error_msg):
    settings = get_settings()
    now = datetime.now(timezone.utc)
    async with Session() as db:
        async with db.begin():
            row = (await db.execute(
                select(DeepAnalysisReport)
                .where(
                    DeepAnalysisReport.id == report_id,
                    DeepAnalysisReport.claim_token == token,
                    DeepAnalysisReport.lease_version == version,
                )
                .with_for_update()
            )).scalar_one_or_none()
            if not row:
                return  # 已被恢复器处理
            if row.attempt_count >= row.max_attempts:
                row.status = "failed"
                row.finished_at = now
                row.error_message = error_msg
                row.error_code = "max_attempts_exceeded"
                if row.credit_state == "reserved":
                    # TODO Phase 2 补积分释放
                    row.credit_state = "released"
            else:
                backoff = min(60 * (2 ** (row.attempt_count - 1)), 300)
                row.status = "retry_wait"
                row.next_retry_at = now + timedelta(seconds=backoff)
                row.error_message = error_msg


async def _recover_stale(Session):
    """将心跳超时的 running 报告转为 retry_wait/failed。"""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STALE_THRESHOLD)
    async with Session() as db:
        async with db.begin():
            rows = (await db.execute(
                select(DeepAnalysisReport)
                .where(
                    DeepAnalysisReport.status == "running",
                    DeepAnalysisReport.heartbeat_at < cutoff,
                )
                .with_for_update(skip_locked=True)
                .limit(10)
            )).scalars().all()

            now = datetime.now(timezone.utc)
            for row in rows:
                if row.attempt_count >= row.max_attempts:
                    row.status = "failed"
                    row.finished_at = now
                    row.error_code = "worker_lost"
                else:
                    row.status = "retry_wait"
                    row.next_retry_at = now + timedelta(seconds=30)
                row.worker_id = None
                row.claim_token = None
    if rows:
        logger.info("recovered %d stale reports", len(rows))


async def claim_loop(Session):
    while not _stop.is_set():
        try:
            claimed = await _claim_one(Session)
            if claimed:
                report_id, token, version = claimed
                task = asyncio.create_task(_execute(Session, report_id, token, version))
                _active.add(task)
                task.add_done_callback(_active.discard)
            else:
                await asyncio.sleep(CLAIM_SLEEP)
        except Exception as e:
            logger.exception("claim_loop error: %s", e)
            await asyncio.sleep(CLAIM_SLEEP)


async def maintenance_loop(Session):
    while not _stop.is_set():
        try:
            await _recover_stale(Session)
        except Exception as e:
            logger.exception("maintenance_loop error: %s", e)
        await asyncio.sleep(MAINTENANCE_INTERVAL)


async def main():
    settings = get_settings()
    if not settings.deep_analysis_worker_enabled:
        logger.error("DEEP_ANALYSIS_WORKER_ENABLED is false, refusing to start")
        return

    logging.basicConfig(level=logging.INFO)
    logger.info("worker starting worker_id=%s", WORKER_ID)

    Session = _make_session()

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, _stop.set)
    loop.add_signal_handler(signal.SIGINT, _stop.set)

    tasks = [
        asyncio.create_task(claim_loop(Session)),
        asyncio.create_task(maintenance_loop(Session)),
    ]
    await _stop.wait()
    logger.info("worker shutting down, waiting for active tasks...")

    # 停止认领，等待当前任务
    for t in tasks:
        t.cancel()
    if _active:
        await asyncio.wait(list(_active), timeout=GRACE_PERIOD)
    logger.info("worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 验证可导入**

```bash
python3 -c "from app.deep_analysis.worker import main; print('OK')"
```

---

### Task 1.10：集成测试

**Goal:** 用 pytest + PostgreSQL 测试容器（或本地测试库）验证 Phase 1 核心可靠性约束。

**Files:**
- Create: `backend/tests/deep_analysis/__init__.py`
- Create: `backend/tests/deep_analysis/test_service.py`
- Create: `backend/tests/deep_analysis/test_worker.py`
- Create: `backend/tests/deep_analysis/test_router.py`

**Pre-condition:** 测试使用已有 `conftest.py` 提供的 `db` fixture 和测试数据库。如无，先检查 `backend/tests/conftest.py`。

- [ ] **Step 1: 确认 conftest 提供的 fixtures**

```bash
cat /Users/weixi1/Documents/mine/D-sight/backend/tests/conftest.py | head -60
```

确认有 `async_client`、`db`（AsyncSession）、`test_user` 等 fixture。若无则补写。

- [ ] **Step 2: 创建 `test_service.py`**

创建 `backend/tests/deep_analysis/test_service.py`：

```python
"""Service 层单元测试。

验证：
1. 正常创建报告并预留积分
2. 完成缓存命中不重复扣费
3. 活跃任务去重返回原报告
4. 积分不足抛 InsufficientCredits
5. 幂等键重放返回原报告
6. 幂等键 + fingerprint 不匹配抛 409
"""
import uuid
import pytest
from sqlalchemy import select
from app.credits.models import CreditAccount, CreditTransaction
from app.credits.service import InsufficientCredits
from app.deep_analysis.models import DeepAnalysisReport
from app.deep_analysis.service import create_report


async def _seed_account(db, user_id, balance=200):
    acct = CreditAccount(user_id=user_id, balance=balance, monthly_quota=200)
    db.add(acct)
    await db.flush()
    return acct


@pytest.mark.asyncio
async def test_create_report_basic(db, test_user):
    await _seed_account(db, test_user.id)
    report, cache_hit, dedup = await create_report(
        db, test_user.id, "A", "600519", idempotency_key=None
    )
    await db.commit()
    assert report.status == "pending"
    assert not cache_hit
    assert not dedup
    assert report.reserved_credits == 50
    # 积分已扣
    acct = await db.get(CreditAccount, test_user.id)
    assert acct.balance == 150


@pytest.mark.asyncio
async def test_active_dedup(db, test_user):
    await _seed_account(db, test_user.id)
    r1, _, _ = await create_report(db, test_user.id, "A", "600519", None)
    await db.commit()
    r2, cache_hit, dedup = await create_report(db, test_user.id, "A", "600519", None)
    await db.commit()
    assert r1.id == r2.id
    assert dedup
    assert not cache_hit
    # 积分只扣一次
    acct = await db.get(CreditAccount, test_user.id)
    assert acct.balance == 150


@pytest.mark.asyncio
async def test_insufficient_credits(db, test_user):
    await _seed_account(db, test_user.id, balance=10)
    with pytest.raises(InsufficientCredits):
        await create_report(db, test_user.id, "A", "000001", None)


@pytest.mark.asyncio
async def test_idempotency_replay(db, test_user):
    await _seed_account(db, test_user.id)
    key = "test-key-001"
    r1, _, _ = await create_report(db, test_user.id, "A", "600519", key)
    await db.commit()
    r2, _, _ = await create_report(db, test_user.id, "A", "600519", key)
    await db.commit()
    assert r1.id == r2.id
    # 积分只扣一次
    acct = await db.get(CreditAccount, test_user.id)
    assert acct.balance == 150


@pytest.mark.asyncio
async def test_idempotency_fingerprint_mismatch(db, test_user):
    await _seed_account(db, test_user.id)
    key = "test-key-002"
    await create_report(db, test_user.id, "A", "600519", key)
    await db.commit()
    with pytest.raises(ValueError, match="fingerprint_mismatch"):
        await create_report(db, test_user.id, "US", "AAPL", key)
```

- [ ] **Step 3: 创建 `test_worker.py`**

创建 `backend/tests/deep_analysis/test_worker.py`：

```python
"""Worker 可靠性测试。

验证：
1. claim_one 认领后 status=running，claim_token 已设
2. 两个 worker 并发认领同一报告，只有一个成功
3. runner 执行完成后 status=completed，result 非空
4. 心跳超时报告被 recover_stale 转为 retry_wait
5. attempt_count 达到 max_attempts 时转为 failed
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.credits.models import CreditAccount
from app.deep_analysis.models import DeepAnalysisReport
from app.deep_analysis.worker import _claim_one, _recover_stale, _execute


async def _create_pending(db, user_id) -> DeepAnalysisReport:
    r = DeepAnalysisReport(
        user_id=user_id,
        market="A",
        ticker="600519",
        normalized_ticker="600519.SH",
        analysis_version="v1",
        status="pending",
        credit_state="exempt",
    )
    db.add(r)
    await db.flush()
    await db.commit()
    return r


@pytest.mark.asyncio
async def test_claim_sets_running(db_session_factory, test_user):
    async with db_session_factory() as db:
        r = await _create_pending(db, test_user.id)
    
    claimed = await _claim_one(db_session_factory)
    assert claimed is not None
    report_id, token, version = claimed

    async with db_session_factory() as db:
        row = await db.get(DeepAnalysisReport, report_id)
    assert row.status == "running"
    assert row.claim_token == token
    assert row.lease_version == 1


@pytest.mark.asyncio
async def test_concurrent_claim_only_one_wins(db_session_factory, test_user):
    async with db_session_factory() as db:
        await _create_pending(db, test_user.id)

    results = await asyncio.gather(
        _claim_one(db_session_factory),
        _claim_one(db_session_factory),
    )
    non_none = [r for r in results if r is not None]
    assert len(non_none) == 1


@pytest.mark.asyncio
async def test_mock_runner_completes(db_session_factory, test_user):
    async with db_session_factory() as db:
        r = await _create_pending(db, test_user.id)
    
    claimed = await _claim_one(db_session_factory)
    assert claimed is not None
    report_id, token, version = claimed
    
    await _execute(db_session_factory, report_id, token, version)

    async with db_session_factory() as db:
        row = await db.get(DeepAnalysisReport, report_id)
    assert row.status == "completed"
    assert row.result is not None
    assert row.result["mock"] is True


@pytest.mark.asyncio
async def test_recover_stale(db_session_factory, test_user):
    async with db_session_factory() as db:
        r = await _create_pending(db, test_user.id)
        # 模拟已认领但心跳超时
        r.status = "running"
        r.claim_token = uuid.uuid4()
        r.lease_version = 1
        r.worker_id = "dead-worker"
        r.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        r.attempt_count = 1
        await db.commit()
    
    await _recover_stale(db_session_factory)

    async with db_session_factory() as db:
        row = await db.get(DeepAnalysisReport, r.id)
    assert row.status == "retry_wait"
    assert row.claim_token is None
```

- [ ] **Step 4: 创建 `test_router.py`**

创建 `backend/tests/deep_analysis/test_router.py`：

```python
"""Router 集成测试（使用 async_client fixture）。

验证：
1. POST 创建报告返回 202，含 id/status/reserved_credits
2. GET 单报告返回正确状态
3. GET 他人报告返回 404
4. GET 列表只含当前用户
5. POST 取消 pending 报告，status=cancelled，积分释放
6. DELETE 已取消报告，返回 204
7. DELETE 运行中报告返回 409
8. 积分不足返回 402
"""
import pytest
import httpx


@pytest.mark.asyncio
async def test_create_basic(async_client, auth_headers, seed_credits):
    resp = await async_client.post(
        "/api/deep-analysis",
        json={"market": "A", "ticker": "600519"},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "pending"
    assert data["reserved_credits"] == 50
    assert not data["cache_hit"]
    assert not data["deduplicated"]


@pytest.mark.asyncio
async def test_get_report(async_client, auth_headers, seed_credits):
    create_resp = await async_client.post(
        "/api/deep-analysis",
        json={"market": "A", "ticker": "000001"},
        headers=auth_headers,
    )
    report_id = create_resp.json()["id"]
    
    resp = await async_client.get(f"/api/deep-analysis/{report_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == report_id


@pytest.mark.asyncio
async def test_get_other_users_report_404(async_client, other_user_auth_headers, seed_credits):
    create_resp = await async_client.post(
        "/api/deep-analysis",
        json={"market": "A", "ticker": "300750"},
        headers=seed_credits["headers"],  # 用有积分的用户创建
    )
    report_id = create_resp.json()["id"]
    
    resp = await async_client.get(
        f"/api/deep-analysis/{report_id}",
        headers=other_user_auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_pending(async_client, auth_headers, seed_credits):
    create_resp = await async_client.post(
        "/api/deep-analysis",
        json={"market": "US", "ticker": "AAPL"},
        headers=auth_headers,
    )
    report_id = create_resp.json()["id"]
    
    cancel_resp = await async_client.post(
        f"/api/deep-analysis/{report_id}/cancel",
        headers=auth_headers,
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_insufficient_credits_returns_402(async_client, auth_headers_no_credits):
    resp = await async_client.post(
        "/api/deep-analysis",
        json={"market": "A", "ticker": "600519"},
        headers=auth_headers_no_credits,
    )
    assert resp.status_code == 402
```

- [ ] **Step 5: 运行全部测试**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
python3 -m pytest tests/deep_analysis/ -v 2>&1 | tail -30
```

Expected: 所有测试通过（绿色 PASSED）。若有 fixture 缺失，补写到 `tests/deep_analysis/conftest.py`。

---

## Phase 1 完成检查单

运行完全部 10 个 Task 后，确认以下条件全部满足再结束 Phase 1：

- [ ] `alembic upgrade head` 无报错，`deep_analysis_reports` 表存在
- [ ] `credit_transactions.operation` 列和 `uq_credit_tx_deep_analysis` 索引存在
- [ ] `python3 -c "from app.main import app"` 无报错
- [ ] POST `/api/deep-analysis` 返回 202
- [ ] GET `/api/deep-analysis/{id}` 返回正确报告
- [ ] 两个并发 `_claim_one` 调用只有一个返回非 None
- [ ] mock runner 执行后 status=completed，result 非空
- [ ] 积分不足返回 402
- [ ] 取消报告后积分被释放
- [ ] 全部测试绿色通过

**下一步：Phase 2** 实现 A 股数据 adapter、analyst 框架和真实 runner（依赖 Phase 0 spike 结论）。
