# 深度多维度分析模块集成设计

**日期：** 2026-07-28  
**状态：** 已审阅  
**作者：** weixi1

---

## 背景与目标

D-sight 现有 Agent 具备单次对话式分析能力，但缺乏结构化的"多视角综合研判"能力。`ai-hedge-fund` 项目抽象了 13 位投资大师 + 技术/基本面 analyst + 风险管理 + 组合决策，形成了成熟的多 agent 分析框架。

目标：将该框架集成进 D-sight，支持 A 股、港股、美股，通过异步后台任务（方案 B）实现：
1. **不阻塞 chat**：触发后台运行，结果持久化可复查
2. **双入口**：专属面板 + chat 工具均可触发
3. **成本可控**：analyst 用 v4-flash，portfolio_manager 用 v4-pro

---

## 架构总览

```
用户（面板 or Chat）
       ↓
POST /api/deep-analysis              ← 触发，立即返回 task_id
       ↓
deep_analysis_reports 表（status=pending）
       ↓
后台 asyncio Task
  ├─ data/adapter.py（统一数据层）
  │    ├─ A 股: akshare
  │    ├─ 港股: akshare hk
  │    └─ 美股: yfinance
  │
  ├─ asyncio.gather → 15 个 analyst（v4-flash）并行
  │    ├─ warren_buffett / ben_graham / ... (13 大师)
  │    ├─ technical_analyst
  │    └─ fundamentals_analyst
  │
  ├─ risk_manager（纯算法，无 LLM）
  └─ portfolio_manager（v4-pro）汇总最终结论
       ↓
结果写入 DB（status=done，result JSONB）
       ↓
GET /api/deep-analysis/{id}          ← 面板轮询 or Chat 工具等待
```

---

## 新增目录结构

```
backend/app/deep_analysis/
├── router.py               # REST 端点注册
├── models.py               # ORM: DeepAnalysisReport
├── schemas.py              # Pydantic 请求/响应结构
├── service.py              # 业务逻辑：触发、查询、4 小时缓存
├── runner.py               # 编排：并行 analyst → risk → portfolio
├── data/
│   ├── adapter.py          # MarketData 统一接口定义
│   ├── a_share.py          # akshare A 股适配
│   ├── hk_share.py         # akshare 港股适配
│   └── us_share.py         # yfinance 美股适配
└── analysts/
    ├── base.py             # BaseAnalyst 抽象类 → AnalystSignal
    ├── warren_buffett.py
    ├── ben_graham.py
    ├── bill_ackman.py
    ├── cathie_wood.py
    ├── charlie_munger.py
    ├── michael_burry.py
    ├── mohnish_pabrai.py
    ├── nassim_taleb.py
    ├── peter_lynch.py
    ├── phil_fisher.py
    ├── rakesh_jhunjhunwala.py
    ├── stanley_druckenmiller.py
    ├── aswath_damodaran.py
    ├── technical.py
    ├── fundamentals.py
    ├── risk_manager.py     # 纯算法，无 LLM
    └── portfolio_manager.py

frontend/src/panels/DeepAnalysis/
├── DeepAnalysisPanel.tsx   # 主面板
├── AnalystCard.tsx         # 单个大师信号卡片
├── ConclusionBanner.tsx    # 最终结论高亮展示
└── HistoryList.tsx         # 历史报告列表

backend/app/agent/tools/deep_analysis.py  # Chat 工具
```

---

## 数据层设计

### 统一数据接口

```python
@dataclass
class MarketData:
    ticker: str
    market: Literal["A", "HK", "US"]
    prices: list[Price]               # 近 90 日日线（date/open/high/low/close/volume）
    financial_metrics: FinancialMetrics  # PE/PB/ROE/负债率/流动比率等
    income_items: IncomeItems         # 营收/净利润/毛利率/近 4~8 期
    balance_items: BalanceItems       # 总资产/总负债/净资产/现金
    cashflow_items: CashflowItems     # 经营/投资/筹资现金流
    news: list[NewsItem]              # 近 30 条新闻（复用现有 news 模块）
```

### 数据源映射

| 字段分类 | A 股 | 港股 | 美股 |
|---|---|---|---|
| 日线价格 | `akshare.stock_zh_a_hist` | `akshare.stock_hk_hist` | `yfinance .history()` |
| 财务比率 | `akshare.stock_financial_analysis_indicator` | `akshare.stock_hk_financial` | `yfinance .info` |
| 利润表 | `akshare.stock_financial_report_sina` (利润) | akshare hk income | `yfinance .financials` |
| 资产负债表 | `akshare.stock_financial_report_sina` (资产) | akshare hk balance | `yfinance .balance_sheet` |
| 现金流量表 | `akshare.stock_financial_report_sina` (现金流) | akshare hk cashflow | `yfinance .cashflow` |
| 新闻 | D-sight `news_query` | 同左 | 同左 |

**注：** akshare 数据字段命名与 financialdatasets.ai 不同，适配层负责归一化到 `MarketData` 结构，analyst 代码不感知数据源差异。

---

## DB Schema

```sql
CREATE TABLE deep_analysis_reports (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
    ticker       VARCHAR(20)  NOT NULL,
    market       VARCHAR(4)   NOT NULL,   -- 'A' | 'HK' | 'US'
    status       VARCHAR(16)  NOT NULL DEFAULT 'pending',
                                          -- pending | running | done | failed
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    result       JSONB,                   -- 完整报告（见报告结构）
    error        TEXT
);

CREATE INDEX idx_dar_user_ticker ON deep_analysis_reports (user_id, ticker, created_at DESC);
CREATE INDEX idx_dar_status ON deep_analysis_reports (status) WHERE status IN ('pending', 'running');
```

---

## API 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/deep-analysis` | 触发分析。Body: `{ticker, market}`。若 4h 内有缓存直接返回已有报告 id。返回 `{id, status}` |
| GET | `/api/deep-analysis/{id}` | 查询单条报告状态+结果 |
| GET | `/api/deep-analysis` | 列出历史报告，支持 `ticker`/`market` 过滤，分页 |
| DELETE | `/api/deep-analysis/{id}` | 删除报告 |

**缓存策略：** 同一用户 + 同一 ticker，4 小时内有 `status=done` 的报告时，POST 直接返回该报告 id，不重新触发。

**积分计费：** 触发一次深度分析扣除固定积分（建议 50 credits，可在 config 配置），查询/删除不计费。

---

## 报告结构（result JSONB）

```json
{
  "ticker": "600519",
  "market": "A",
  "generated_at": "2026-07-28T10:00:00Z",
  "analyst_signals": {
    "warren_buffett":          {"signal": "bullish",  "confidence": 82, "reasoning": "强护城河，合理估值"},
    "ben_graham":              {"signal": "neutral",  "confidence": 61, "reasoning": "安全边际不足"},
    "bill_ackman":             {"signal": "bullish",  "confidence": 75, "reasoning": "..."},
    "cathie_wood":             {"signal": "bearish",  "confidence": 55, "reasoning": "..."},
    "charlie_munger":          {"signal": "bullish",  "confidence": 80, "reasoning": "..."},
    "michael_burry":           {"signal": "neutral",  "confidence": 58, "reasoning": "..."},
    "mohnish_pabrai":          {"signal": "bullish",  "confidence": 77, "reasoning": "..."},
    "nassim_taleb":            {"signal": "neutral",  "confidence": 50, "reasoning": "..."},
    "peter_lynch":             {"signal": "bullish",  "confidence": 72, "reasoning": "..."},
    "phil_fisher":             {"signal": "bullish",  "confidence": 68, "reasoning": "..."},
    "rakesh_jhunjhunwala":     {"signal": "bullish",  "confidence": 79, "reasoning": "..."},
    "stanley_druckenmiller":   {"signal": "bearish",  "confidence": 65, "reasoning": "..."},
    "aswath_damodaran":        {"signal": "neutral",  "confidence": 63, "reasoning": "..."},
    "technical_analyst":       {"signal": "bearish",  "confidence": 70, "reasoning": "..."},
    "fundamentals_analyst":    {"signal": "bullish",  "confidence": 74, "reasoning": "..."}
  },
  "risk": {
    "volatility_percentile": 42,
    "position_limit_pct": 8.5
  },
  "conclusion": {
    "action": "buy",
    "confidence": 74,
    "reasoning": "9/15 分析师看多，基本面稳健，技术面短期承压但中期趋势向上",
    "bull_count": 9,
    "bear_count": 3,
    "neutral_count": 3
  }
}
```

---

## Chat 工具集成

注册为现有 8 个 Agent 工具之一，在 `build.py` 中引入：

```python
# backend/app/agent/tools/deep_analysis.py

@tool
async def deep_analyst_report(ticker: str, market: str) -> str:
    """
    对指定股票进行深度多维度分析（13 位投资大师视角 + 技术 + 基本面 + 风险管理）。
    返回各分析师信号汇总和最终投资建议。
    
    Args:
        ticker: 股票代码（A 股如 600519，港股如 00700，美股如 AAPL）
        market: 市场类型，'A'=A 股，'HK'=港股，'US'=美股
    """
    # 1. 检查 4h 内缓存（直接查 DB）
    # 2. 无缓存则触发新任务并等待，最多 90s
    # 3. 超时返回提示文案，用户可去面板查看
    # 4. 完成则返回结构化摘要（不返回完整 JSON，控制 token）
```

返回给 Agent 的摘要格式（控制在 500 token 以内）：
```
【深度分析】600519 贵州茅台（A 股）
看多 9 / 看空 3 / 中性 3

主要观点：
• Warren Buffett（82% 信心）：bullish — 强护城河，合理估值
• 技术分析（70% 信心）：bearish — 短期均线系统走弱
• 基本面（74% 信心）：bullish — ROE 持续高位，现金流充裕

风险：波动率百分位 42，建议仓位上限 8.5%
综合结论：买入（信心 74%）— 9/15 分析师看多，基本面稳健，技术面短期承压但中期趋势向上
```

---

## 前端面板

在 `frontend/src/panels/` 新增 `DeepAnalysis/` 面板，与 FundArb/News/Social 同级挂载：

**交互流程：**
1. 输入股票代码 + 选择市场（A/HK/US）→ 点击"开始分析"
2. 状态轮询（每 3 秒 GET，running 时显示动效进度条）
3. 完成后展示：
   - 顶部结论 Banner（买入/卖出/持有，信心度，看多/空/中性统计）
   - 15 张大师信号卡（bullish=绿，bearish=红，neutral=灰，含 reasoning 展开）
   - 风险信息（波动率百分位，仓位上限）
4. 底部历史报告列表（可点击复查）

---

## LLM 模型配置

| 阶段 | 模型 | 理由 |
|---|---|---|
| 15 个 analyst 并行 | `deepseek-v4-flash` | 结构化输出任务，flash 足够；成本降 5–8 倍 |
| portfolio_manager | `deepseek-v4-pro` | 综合判断，需要更强推理 |
| risk_manager | 无 LLM | 纯算法（波动率百分位 + 相关性矩阵） |

预估单次分析 token 消耗：约 3–6 万 tokens（flash）+ 3–5k tokens（pro），对应约 30–65 credits。

---

## 实施顺序

1. **数据层**：`data/adapter.py` 接口定义 + A 股适配（先跑通一个市场，验证字段覆盖）
2. **analyst 移植**：从 ai-hedge-fund 逐个移植，重点适配数据字段映射；先移植 3–5 个验证流程
3. **runner + DB + API**：任务编排、状态管理、REST 接口
4. **Chat 工具注册**：在 `build.py` 引入 `deep_analyst_report`
5. **前端面板**：DeepAnalysis 面板开发
6. **港股 + 美股适配**：补全剩余两个市场的数据适配器
7. **积分计费接入**：在 POST 触发时扣费

每步可独立测试，不影响现有功能。

---

## 风险与约束

- **akshare 数据质量**：财务报表字段名称可能因 akshare 版本变化，需做防御性解析
- **港股财务数据**：akshare 港股财务数据覆盖不如 A 股完整，部分大师需降级处理（缺字段时 confidence 降权）
- **并发限制**：15 个 analyst 同时调 DeepSeek API，需确认 rate limit；可加 semaphore 控制并发数（建议 ≤ 10）
- **超时**：单次分析设 120s 超时保护，超时标记 failed
