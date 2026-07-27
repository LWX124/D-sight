# Fund Arb 对账重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `job.py` 中静默的 `_calibrate_ref()` 改造为结构化对账模块，差异持久化入库、超动态阈值自动修正内存估值、支持定时和手动两种触发方式。

**Architecture:** 新增 `reconciliation.py` 承载所有对账逻辑（纯函数层 + 编排层），`models.py` 新增 `FundArbReconciliation` 表，`snapshot.py` 暴露 `update_est_nav`，`job.py` 替换旧调用，`router.py` 新增手动触发端点。

**Tech Stack:** Python 3.12, SQLAlchemy 2 async, FastAPI, PostgreSQL (plain ORM insert), subprocess/curl (asyncio.to_thread 包装)

## Global Constraints

- 所有 DB 操作使用 async SQLAlchemy session，与现有 `_upsert_daily` 风格一致
- 单点失败隔离：单个基金对账失败不中断整体流程
- `fetch_ref_nav` 失败时 skip，不重试（与现有 `_calibrate_ref` 行为一致）
- 动态阈值样本 < 5 时 fallback 到 0.01（1%）
- 终端输出格式固定（见 spec）

---

## 文件结构

| 文件 | 操作 | 职责 |
|---|---|---|
| `backend/app/fund_arb/reconciliation.py` | 新建 | 对账纯函数 + 编排入口 + ref 抓取 |
| `backend/app/fund_arb/models.py` | 修改 | 新增 `FundArbReconciliation` ORM |
| `backend/app/fund_arb/snapshot.py` | 修改 | 新增 `SnapshotStore.update_est_nav` |
| `backend/app/fund_arb/job.py` | 修改 | 替换 `_calibrate_ref` 调用，迁移 `_parse_ref_page`/`_REF_PAGES` |
| `backend/app/fund_arb/router.py` | 修改 | 新增 `POST /api/fund-arb/reconcile` |
| `backend/tests/fund_arb/test_reconciliation.py` | 新建 | 单元测试 |

---

### Task 1: 新增 FundArbReconciliation ORM + SnapshotStore.update_est_nav

**Files:**
- Modify: `backend/app/fund_arb/models.py`
- Modify: `backend/app/fund_arb/snapshot.py`
- Test: `backend/tests/fund_arb/test_reconciliation.py`

**Interfaces:**
- Produces: `FundArbReconciliation` ORM class with fields: `fund_code`, `run_at`, `local_est_nav`, `ref_est_nav`, `deviation_pct`, `threshold_used`, `action`
- Produces: `SnapshotStore.update_est_nav(fund_code: str, value: float) -> None`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/fund_arb/test_reconciliation.py
from app.fund_arb.snapshot import SnapshotStore, FundSnapshot
import datetime as dt

def _make_snap(code: str, est: float) -> FundSnapshot:
    return FundSnapshot(
        fund_code=code, fund_name="test", category="qdii_us_eu",
        price=1.0, price_pct=0.0, amount=None,
        est_nav=est, premium=None, nav=est, nav_date=dt.date.today(),
        err_5d=None, low_confidence=False, approx=False,
        purchase_status=None, redemption_status=None, purchase_limit=None,
        as_of=dt.datetime.now(dt.UTC), source="realtime",
    )

def test_update_est_nav():
    store = SnapshotStore()
    store.update([_make_snap("513500", 1.2341)])
    store.update_est_nav("513500", 1.2389)
    assert store._snaps["513500"].est_nav == 1.2389

def test_update_est_nav_missing_code():
    store = SnapshotStore()
    store.update_est_nav("999999", 1.0)  # 不存在时静默忽略
```

- [ ] **Step 2: 运行确认失败**

```bash
cd backend && python -m pytest tests/fund_arb/test_reconciliation.py::test_update_est_nav -v
```
预期：`AttributeError: 'SnapshotStore' object has no attribute 'update_est_nav'`

- [ ] **Step 3: 在 models.py 末尾追加 FundArbReconciliation**

在 `backend/app/fund_arb/models.py` 末尾追加：

```python
class FundArbReconciliation(Base):
    """对账记录（每次 run_reconciliation 写入）。"""

    __tablename__ = "fund_arb_reconciliation"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fund_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    run_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    local_est_nav: Mapped[float] = mapped_column(Float, nullable=False)
    ref_est_nav: Mapped[float] = mapped_column(Float, nullable=False)
    deviation_pct: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_used: Mapped[float] = mapped_column(Float, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # "none" | "corrected"
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4: 在 snapshot.py 的 SnapshotStore 类中追加 update_est_nav**

在 `SnapshotStore.rows` 方法之后追加：

```python
    def update_est_nav(self, fund_code: str, value: float) -> None:
        snap = self._snaps.get(fund_code)
        if snap is None:
            return
        self._snaps[fund_code] = FundSnapshot(**{**snap.__dict__, "est_nav": round(value, 4)})
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd backend && python -m pytest tests/fund_arb/test_reconciliation.py -v
```
预期：2 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/fund_arb/models.py backend/app/fund_arb/snapshot.py backend/tests/fund_arb/test_reconciliation.py
git commit -m "feat(fund_arb): FundArbReconciliation ORM + SnapshotStore.update_est_nav"
```

---

### Task 2: 新建 reconciliation.py（纯函数层）

**Files:**
- Create: `backend/app/fund_arb/reconciliation.py`
- Test: `backend/tests/fund_arb/test_reconciliation.py`

**Interfaces:**
- Consumes: 无外部依赖（纯函数）
- Produces:
  - `ReconcileResult(deviation_pct: float, action: str, corrected_value: float)`
  - `compute_dynamic_threshold(fund_code: str, session) -> float`（async）
  - `reconcile_fund(fund_code: str, local_est: float, ref_est: float, threshold: float) -> ReconcileResult`

- [ ] **Step 1: 写失败测试**

在 `test_reconciliation.py` 追加：

```python
from app.fund_arb.reconciliation import ReconcileResult, reconcile_fund

def test_reconcile_fund_no_action():
    r = reconcile_fund("513500", 1.2341, 1.2350, 0.01)
    assert r.action == "none"
    assert r.corrected_value == 1.2341

def test_reconcile_fund_corrected():
    r = reconcile_fund("513500", 1.2341, 1.2389, 0.003)
    assert r.action == "corrected"
    assert r.corrected_value == 1.2389
    assert abs(r.deviation_pct - (1.2341 / 1.2389 - 1) * 100) < 1e-6

def test_reconcile_fund_negative_deviation():
    r = reconcile_fund("513500", 1.2389, 1.2341, 0.003)
    assert r.action == "corrected"
    assert r.corrected_value == 1.2341
```

- [ ] **Step 2: 运行确认失败**

```bash
cd backend && python -m pytest tests/fund_arb/test_reconciliation.py::test_reconcile_fund_no_action -v
```
预期：`ModuleNotFoundError` 或 `ImportError`

- [ ] **Step 3: 创建 reconciliation.py（纯函数部分）**

```python
# backend/app/fund_arb/reconciliation.py
import datetime as dt
import logging
import statistics
import subprocess
from dataclasses import dataclass

from sqlalchemy import select

from app.fund_arb.models import FundArbDaily

_log = logging.getLogger(__name__)

_FALLBACK_THRESHOLD = 0.01
_THRESHOLD_WINDOW = 30
_THRESHOLD_SIGMA = 3.0


@dataclass
class ReconcileResult:
    deviation_pct: float
    action: str  # "none" | "corrected"
    corrected_value: float


def reconcile_fund(
    fund_code: str, local_est: float, ref_est: float, threshold: float
) -> ReconcileResult:
    deviation_pct = (local_est / ref_est - 1.0) * 100.0
    if abs(deviation_pct) > threshold * 100.0:
        return ReconcileResult(deviation_pct=deviation_pct, action="corrected", corrected_value=ref_est)
    return ReconcileResult(deviation_pct=deviation_pct, action="none", corrected_value=local_est)


async def compute_dynamic_threshold(fund_code: str, session) -> float:
    rows = (await session.execute(
        select(FundArbDaily.valuation_error)
        .where(
            FundArbDaily.fund_code == fund_code,
            FundArbDaily.valuation_error.is_not(None),
        )
        .order_by(FundArbDaily.date.desc())
        .limit(_THRESHOLD_WINDOW)
    )).scalars().all()
    if len(rows) < 5:
        return _FALLBACK_THRESHOLD
    return statistics.stdev(rows) * _THRESHOLD_SIGMA / 100.0
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && python -m pytest tests/fund_arb/test_reconciliation.py -v
```
预期：5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/fund_arb/reconciliation.py backend/tests/fund_arb/test_reconciliation.py
git commit -m "feat(fund_arb): reconciliation 纯函数层（ReconcileResult + compute_dynamic_threshold）"
```

---

### Task 3: reconciliation.py 编排层（fetch_ref_nav + run_reconciliation）

**Files:**
- Modify: `backend/app/fund_arb/reconciliation.py`
- Modify: `backend/app/fund_arb/job.py`（迁移 `_parse_ref_page` 和 `_REF_PAGES`）

**Interfaces:**
- Consumes: `ReconcileResult`, `compute_dynamic_threshold`, `reconcile_fund`（Task 2）；`FundArbReconciliation`（Task 1）；`SnapshotStore.update_est_nav`（Task 1）
- Produces:
  - `fetch_ref_nav_all() -> dict[str, tuple[float, float]]`（async，批量拉取所有页面，返回 `{sina_symbol_upper: (est, premium)}`）
  - `run_reconciliation(session_factory) -> str`（async，返回格式化摘要字符串）

- [ ] **Step 1: 将 `_parse_ref_page` 和 `_REF_PAGES` 从 job.py 迁移到 reconciliation.py**

在 `reconciliation.py` 末尾追加（从 `job.py` 原样复制，不改逻辑）：

```python
_REF_PAGES = [
    "https://www.palmmicro.com/woody/res/qdiicn.php",
    "https://www.palmmicro.com/woody/res/chinaindexcn.php",
    "https://www.palmmicro.com/woody/res/chinafuturecn.php",
    "https://www.palmmicro.com/woody/res/qdiimixcn.php",
    "https://www.palmmicro.com/woody/res/qdiihkcn.php",
    "https://www.palmmicro.com/woody/res/qdiieucn.php",
]


def _parse_ref_page(html: str) -> dict[str, tuple[float, float]]:
    import re
    out: dict[str, tuple[float, float]] = {}
    for m in re.finditer(
        r'>([SZ][HZ]\d{6})</a></td>'
        r'<td[^>]*><font[^>]*>([\d.]+)</font></td>'
        r'<td[^>]*>\d{4}-\d{2}-\d{2}</td>'
        r'<td[^>]*><font[^>]*>([-\d.]+)%</font>',
        html,
    ):
        sym, est, prem = m.group(1), float(m.group(2)), float(m.group(3))
        out[sym] = (est, prem)
    return out


async def fetch_ref_nav_all() -> dict[str, tuple[float, float]]:
    ref_data: dict[str, tuple[float, float]] = {}
    for url in _REF_PAGES:
        try:
            result = subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=30)
            ref_data.update(_parse_ref_page(result.stdout))
        except Exception:
            _log.exception("fund_arb 参考网站抓取失败：%s", url)
    return ref_data
```

- [ ] **Step 2: 在 reconciliation.py 追加 run_reconciliation**

```python
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.fund_arb.models import FundArbFund, FundArbReconciliation
from app.fund_arb.snapshot import get_store


async def run_reconciliation(session_factory) -> str:
    run_at = dt.datetime.now(dt.timezone.utc)
    ref_data = await fetch_ref_nav_all()
    if not ref_data:
        _log.warning("fund_arb 参考网站解析结果为空，跳过对账")
        return "[reconcile] 参考网站无数据，跳过"

    async with session_factory() as db:
        funds = (await db.execute(
            select(FundArbFund).where(FundArbFund.enabled.is_(True))
        )).scalars().all()

    fund_map = {f.sina_symbol.upper(): f for f in funds}
    lines: list[str] = []
    total = corrected = errors = 0

    for sym_upper, (ref_est, ref_prem) in ref_data.items():
        fund = fund_map.get(sym_upper)
        if fund is None:
            continue
        total += 1
        try:
            async with session_factory() as db:
                threshold = await compute_dynamic_threshold(fund.fund_code, db)
                snap = get_store()._snaps.get(fund.fund_code)
                local_est = snap.est_nav if snap and snap.est_nav else None
                if local_est is None:
                    continue
                result = reconcile_fund(fund.fund_code, local_est, ref_est, threshold)
                stmt = pg_insert(FundArbReconciliation).values(
                    fund_code=fund.fund_code,
                    run_at=run_at,
                    local_est_nav=local_est,
                    ref_est_nav=ref_est,
                    deviation_pct=result.deviation_pct,
                    threshold_used=threshold,
                    action=result.action,
                )
                stmt = stmt.on_conflict_do_nothing()
                await db.execute(stmt)
                await db.commit()
            if result.action == "corrected":
                get_store().update_est_nav(fund.fund_code, ref_est)
                corrected += 1
            sign = "+" if result.deviation_pct >= 0 else ""
            lines.append(
                f"{fund.fund_code:<8} {local_est:<10.4f} {ref_est:<10.4f} "
                f"{sign}{result.deviation_pct:.2f}%{'':<4} "
                f"{threshold * 100:.2f}%{'':<4} {result.action}"
            )
        except Exception:
            _log.exception("fund_arb 对账失败：%s", fund.fund_code)
            errors += 1

    header = (
        f"[reconcile] {run_at.astimezone(dt.timezone(dt.timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')}"
        f"  total={total}  corrected={corrected}  errors={errors}"
    )
    col = "fund     local_est  ref_est    deviation  threshold  action"
    summary = "\n".join([header, col] + lines)
    print(summary)
    return summary
```

- [ ] **Step 3: 在 job.py 中删除 `_parse_ref_page`、`_REF_PAGES`、`_calibrate_ref`，替换调用**

将 `job.py` 中 `morning_job` 末尾的：
```python
    try:
        await _calibrate_ref()
    except Exception:
        _log.exception("fund_arb 参考网站校对失败")
```
替换为：
```python
    try:
        from app.fund_arb.reconciliation import run_reconciliation
        await run_reconciliation(session_factory)
    except Exception:
        _log.exception("fund_arb 对账失败")
```

同时删除 `job.py` 中的 `_parse_ref_page`、`_REF_PAGES`、`_calibrate_ref` 三个定义（共约 70 行）。

- [ ] **Step 4: 运行测试确认无回归**

```bash
cd backend && python -m pytest tests/fund_arb/ -v
```
预期：全部 passed，无 import error

- [ ] **Step 5: Commit**

```bash
git add backend/app/fund_arb/reconciliation.py backend/app/fund_arb/job.py
git commit -m "feat(fund_arb): run_reconciliation 编排层，替换 _calibrate_ref"
```

---

### Task 4: router.py 新增手动触发端点

**Files:**
- Modify: `backend/app/fund_arb/router.py`
- Test: `backend/tests/fund_arb/test_reconciliation.py`

**Interfaces:**
- Consumes: `run_reconciliation(session_factory) -> str`（Task 3）
- Produces: `POST /api/fund-arb/reconcile` → `{"summary": "..."}`

- [ ] **Step 1: 写失败测试**

在 `test_reconciliation.py` 追加：

```python
from httpx import AsyncClient
from app.main import app
import pytest

@pytest.mark.anyio
async def test_reconcile_endpoint_forbidden():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/api/fund-arb/reconcile")
    assert resp.status_code in (401, 403)
```

- [ ] **Step 2: 运行确认失败**

```bash
cd backend && python -m pytest tests/fund_arb/test_reconciliation.py::test_reconcile_endpoint_forbidden -v
```
预期：`404 Not Found`（端点不存在）

- [ ] **Step 3: 在 router.py 追加端点**

在 `router.py` 末尾追加（在现有 import 中补充 `get_sessionmaker`，已存在则跳过）：

```python
from app.fund_arb.reconciliation import run_reconciliation as _run_reconciliation


@router.post("/reconcile")
async def reconcile(user: User = Depends(get_current_user)) -> dict:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可手动触发对账")
    summary = await _run_reconciliation(get_sessionmaker())
    return {"summary": summary}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && python -m pytest tests/fund_arb/ -v
```
预期：全部 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/fund_arb/router.py backend/tests/fund_arb/test_reconciliation.py
git commit -m "feat(fund_arb): POST /api/fund-arb/reconcile 手动触发对账"
```
