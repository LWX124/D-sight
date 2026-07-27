# 基金套利估值校对设计

**日期：** 2026-07-22  
**分支：** fund-arb  
**状态：** 待审阅

---

## 背景

参考网站 https://www.palmmicro.com/woody/res/qdiicn.php 提供 33 只 QDII 基金的官方 EST 和参考 EST，是我们估值准确性的外部基准。目前系统没有与该网站的自动对比机制。

---

## 目标

1. **一次性全量校对**：抓取参考网站所有基金的 EST 和溢价，与数据库当前值对比，终端打印差异报告，同时落库。
2. **持续监控**：每日早盘前自动对比，偏差超过 0.5% 时写入告警日志。

---

## 数据来源分析

参考网站列表页 `qdiicn.php` 一次返回全部 33 只基金，包含：

| 字段 | 含义 |
|------|------|
| 官方 EST | 用昨日净值 + 校准因子计算的估值 |
| 参考 EST | 用实时价格计算的估值（盘中更准） |
| 官方溢价 | (市价 / 官方EST − 1) × 100% |
| 参考溢价 | (市价 / 参考EST − 1) × 100% |

**结论**：不需要逐个抓详情页，列表页已包含所有需要的校对数据。

---

## 数据模型变更

在 `FundArbDaily` 增加两个可空字段：

```python
ref_est_nav: Mapped[float | None] = mapped_column(Float)      # 参考网站官方EST
ref_premium: Mapped[float | None] = mapped_column(Float)      # 参考网站官方溢价(%)
```

对应一条 Alembic migration。

**选择官方 EST 而非参考 EST 的原因**：官方 EST 基于昨日净值校准，与我们的 `est_nav_close` 口径一致，适合日终对账。

---

## 一次性校对脚本

文件：`backend/scripts/calibrate_ref.py`

流程：
1. curl 抓取 `qdiicn.php` HTML
2. 正则解析 EST 表格（`<table>` 中含代码、官方EST、溢价的行）
3. 查询数据库最新一条 `FundArbDaily`（有 `est_nav_close` 的）
4. 计算偏差 `diff = (our_est / ref_est − 1) × 100%`
5. 终端打印对比表（含偏差列，超过 0.5% 标红）
6. upsert `ref_est_nav` / `ref_premium` 到对应日期行

输出示例：
```
基金代码   我方EST   参考EST   偏差%   我方溢价   参考溢价   状态
SZ162411   0.918     0.918     0.00%   1.31%      1.28%      ✓
SH513100   2.148     2.155    -0.32%   0.85%      0.52%      ✓
...
```

---

## 持续监控

在 `job.py` 的 `morning_job()` 末尾增加 `_calibrate_ref()` 函数：

1. curl 抓取列表页（与脚本复用同一解析函数）
2. 与当日 `est_nav_close` 对比
3. 偏差 > 0.5% 的基金写 `_log.warning()`，同时 upsert `ref_est_nav` / `ref_premium`

不引入新的告警基础设施，日志告警足够（现有 Sentry/日志聚合可捕获 WARNING 级别）。

---

## 文件变更清单

| 文件 | 变更 |
|------|------|
| `backend/app/fund_arb/models.py` | 增加 `ref_est_nav`, `ref_premium` 字段 |
| `backend/alembic/versions/xxx_ref_est.py` | 新 migration |
| `backend/app/fund_arb/job.py` | 增加 `_calibrate_ref()` + 集成到 `morning_job` |
| `backend/scripts/calibrate_ref.py` | 新增一次性校对脚本 |

---

## 不在范围内

- 参考网站的"参考 EST"（实时）字段：盘中才有意义，不落库
- 详情页的校准因子历史：已有 `FundArbFactor` 表覆盖
- 非 QDII 基金（白银、债券）：参考网站不覆盖，跳过

---

## 风险

- 参考网站 HTML 结构变更会导致解析失败：解析失败时静默跳过（不影响主流程），日志记录
- 33 只 vs 我们 92 只：未被参考网站覆盖的基金不做对比，不报错
