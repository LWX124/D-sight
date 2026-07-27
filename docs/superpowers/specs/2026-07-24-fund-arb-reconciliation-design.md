# Fund Arb 对账重构设计

## 目标

将 `job.py` 中静默的 `_calibrate_ref()` 改造为结构化对账模块：差异持久化入库、超阈值自动修正本地估值、支持定时和手动两种触发方式。

## 架构

### 新增文件：`reconciliation.py`

纯函数层（无 IO）：

- `compute_dynamic_threshold(fund_code, session) -> float`
  查询 `FundArbDaily.valuation_error` 最近 30 天，计算滚动标准差 × 3。
  样本 < 5 时 fallback 到 0.01（1%）。

- `reconcile_fund(fund_code, local_est, ref_est, threshold) -> ReconcileResult`
  返回 `(deviation_pct, action: "none"|"corrected", corrected_value)`。
  `action = "corrected"` 当且仅当 `abs(deviation_pct) > threshold`。

编排层（有 IO）：

- `fetch_ref_nav_all() -> dict[str, tuple[float, float]]`
  批量拉取所有 palmmicro.com 页面，返回 `{sina_symbol_upper: (est, premium)}`。
  （实现偏差：设计为按基金逐个拉取，实现改为批量拉全部页面再匹配，更高效。）

- `run_reconciliation(session_factory) -> str`
  遍历所有基金，调用上述纯函数，写 `FundArbReconciliation` 表，
  若 `action == "corrected"` 则更新 `SnapshotStore` 内存值，
  返回格式化摘要字符串供终端打印。
  （实现偏差：参数为 session_factory 而非 session，因循环内需多个独立事务；
  返回值为 str 而非结构体，调用方只需打印/透传文本。）

### 新增 DB 表：`FundArbReconciliation`

```
fund_code       VARCHAR  NOT NULL
run_at          DATETIME NOT NULL
local_est_nav   FLOAT    NOT NULL
ref_est_nav     FLOAT    NOT NULL
deviation_pct   FLOAT    NOT NULL
threshold_used  FLOAT    NOT NULL
action          VARCHAR  NOT NULL  -- "none" | "corrected"
```

索引：`(fund_code, run_at)`

### 修改点

| 文件 | 改动 |
|---|---|
| `models.py` | 新增 `FundArbReconciliation` ORM 类 |
| `job.py` | `morning_job()` 替换 `_calibrate_ref()` 为 `run_reconciliation()` + 打印摘要 |
| `router.py` | 新增 `POST /api/fund-arb/reconcile`（手动触发，admin-only） |
| `snapshot.py` | 暴露 `update_est_nav(fund_code, value)` 供 `run_reconciliation` 修正内存值 |

### 终端输出格式

```
[reconcile] 2026-07-24 09:15  total=12  corrected=2  errors=0
fund     local_est  ref_est  deviation  threshold  action
513500   1.2341     1.2389   +0.39%     0.31%      corrected
159920   0.8821     0.8819   -0.02%     0.28%      none
```

## 数据流

```
morning_job / POST /reconcile
  └─ run_reconciliation(session_factory)
       ├─ fetch_ref_nav_all()               # IO: palmmicro（批量拉取所有页面）
       ├─ compute_dynamic_threshold(...)    # IO: DB read
       ├─ reconcile_fund(...)               # pure
       ├─ INSERT FundArbReconciliation      # IO: DB write（plain insert，非 upsert）
       └─ SnapshotStore.update_est_nav(...) # IO: memory write (if corrected)
```

## 不在范围内

- 不修改 `calibration.py`（beta 校准逻辑独立）
- 不新增前端展示（历史对账记录可通过现有 `/history` 扩展，后续再做）
- 不处理 `fetch_ref_nav` 失败时的重试（沿用现有 skip 逻辑）
