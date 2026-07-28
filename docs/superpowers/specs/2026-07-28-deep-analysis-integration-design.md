# 深度多维度分析模块集成设计

**日期：** 2026-07-28
**状态：** 待最终审阅
**作者：** weixi1

---

## 1. 背景、目标与成功标准

D-sight 现有 Agent 能完成单轮对话式投研，但缺少可复查、可比较、可恢复的多视角结构化分析。`ai-hedge-fund` 提供了 13 种投资方法论、技术与基本面分析、风险约束和最终汇总的参考实现。

本模块将这些**投资方法论**集成进 D-sight，而不是让模型冒充真实人物。首期支持 A 股、港股和美股，并提供面板与 Chat 两个入口。

### 1.1 已确认目标

1. **三市场支持**：A 股、港股、美股使用统一输入输出契约。
2. **异步持久化**：触发后立即返回；任务可在重启后恢复，结果可长期复查。
3. **双入口**：专属面板与 Chat 使用同一个服务和同一份报告。
4. **成本分层**：analyst 使用 `deepseek-v4-flash`，portfolio manager 使用 `deepseek-v4-pro`，risk engine 不使用 LLM。
5. **可解释、可审计**：所有关键数字带来源、报告期、币种、单位和数据时间。
6. **失败可见**：数据不足、单个 analyst 失败和任务失败不得伪装为有效结论。

### 1.2 “更准确”的定义

多 agent 数量本身不等于准确。生产验收以以下指标为准：

- 数据字段标准化正确率和数据新鲜度；
- 同一输入重复运行时的信号稳定性；
- 所有结论能否追溯到输入证据；
- 非法 LLM 输出被拦截的比例；
- 固定评估集上的方向判断、置信度校准和人工评分；
- 与当前单 Agent 基线相比是否有可测量提升。

未通过评估门槛前，功能标记为 Beta，不宣称能提高投资收益。

### 1.3 非目标

首期不包含：

- 自动交易、下单或账户托管；
- 个性化投资顾问服务；
- 基于用户完整持仓的组合优化；
- 高频或盘中交易信号；
- 对 `ai-hedge-fund` 代码未经许可证核验的直接复制。

---

## 2. 核心架构

```text
面板 POST /api/deep-analysis             Chat: start_deep_analysis
                  │                               │
                  └────────── application service ┘
                                  │
                  原子事务：幂等检查 + 积分预授权 + 创建任务
                                  │
                                  ▼
             deep_analysis_reports(status=pending)
                                  │
                       PostgreSQL worker claim
                  SELECT ... FOR UPDATE SKIP LOCKED
                                  │
                                  ▼
                           独立 worker 进程
              ┌───────────────────┼──────────────────┐
              │                   │                  │
      MarketData adapters   analyst fan-out    heartbeat/retry
       A / HK / US          并发上限控制
              │                   │
              └─────────── validated signals
                                  │
                      deterministic risk engine
                                  │
                    portfolio manager (v4-pro)
                                  │
             原子事务：保存结果 + 状态完成 + 积分结算
                                  │
                 GET /api/deep-analysis/{report_id}
                    面板轮询 / Chat 查询 / 历史复查
```

### 2.1 为什么不用进程内 `asyncio.create_task`

API 进程内任务在部署、崩溃和进程回收后会丢失，也无法在多 worker 环境中可靠防重。首期采用 **PostgreSQL 持久化任务队列 + 独立 worker**：

- 不额外引入 Redis/Celery 的运维复杂度；
- 使用现有 PostgreSQL；
- 支持原子认领、心跳、重试和崩溃恢复；
- 未来吞吐量超过 PostgreSQL 队列能力时，可在不改变业务接口的前提下迁移到 Celery、Dramatiq 或云任务队列。

APScheduler 只负责周期性扫描和维护，不执行报告主体。

### 2.2 模块边界

```text
backend/app/deep_analysis/
├── router.py                  # HTTP、鉴权、参数校验；不含业务编排
├── schemas.py                 # API 请求与响应
├── models.py                  # ORM
├── service.py                 # 幂等、权限、缓存、计费事务
├── worker.py                  # 任务认领、心跳、重试、恢复
├── runner.py                  # 单份报告的编排
├── registry.py                # analyst 注册、版本与最低覆盖规则
├── llm.py                     # 按角色创建模型，复用现有重试包装
├── data/
│   ├── models.py              # 统一数据与证据契约
│   ├── base.py                # MarketDataAdapter Protocol
│   ├── normalize.py           # ticker、币种、单位和字段标准化
│   ├── a_share.py             # akshare A 股适配
│   ├── hk_share.py            # 经验证的数据源适配
│   └── us_share.py            # yfinance 美股适配
└── analysts/
    ├── base.py                # 输入输出契约和校验
    ├── value/                 # 价值类方法论
    ├── growth/                # 成长类方法论
    ├── macro/                 # 宏观与趋势类方法论
    ├── technical.py
    ├── fundamentals.py
    ├── risk.py                # 纯算法
    └── portfolio.py

backend/app/agent/tools/deep_analysis.py
frontend/src/panels/DeepAnalysis/
backend/tests/deep_analysis/
```

每个模块只依赖稳定契约：数据适配器不感知 analyst，analyst 不感知市场数据源，HTTP 层不感知 runner 内部步骤。

---

## 3. 任务状态机与可靠执行

### 3.1 状态机

```text
pending → running → completed
   │          ├──→ retry_wait → pending
   │          ├──→ failed
   │          └──→ cancelled
   └──────────────→ cancelled
```

允许状态：

- `pending`：已创建，等待 worker；
- `running`：worker 已认领；
- `retry_wait`：可恢复错误，等待下一次尝试；
- `completed`：报告已持久化并通过 Schema 校验；
- `failed`：已达重试上限或不可恢复错误；
- `cancelled`：用户取消，worker 在阶段边界停止。

所有状态转换使用带旧状态条件的原子 `UPDATE`，避免多个 worker 重复完成或失败覆盖成功。

### 3.2 任务认领

worker 在短事务内执行：

```sql
SELECT id
FROM deep_analysis_reports
WHERE status IN ('pending', 'retry_wait')
  AND next_retry_at <= now()
ORDER BY next_retry_at, created_at
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

认领后生成新的 `claim_token`、递增 `lease_version` 并写入：

- `status=running`
- `worker_id`
- `claim_token/lease_version`
- `started_at`
- `heartbeat_at`
- `attempt_count=attempt_count+1`

`retry_wait` 不需要另一个 scheduler 转回 `pending`；独立 worker 的 claim loop 直接认领已到 `next_retry_at` 的 `retry_wait`。失联扫描也由 worker maintenance loop 执行，并用 PostgreSQL advisory lock 保证同一时刻只有一个维护者。API 进程中的 APScheduler 不参与本任务队列。

### 3.3 心跳、恢复与重试

- worker 每 15 秒更新一次 `heartbeat_at`；
- `running` 且心跳超过 60 秒未更新的任务视为失联；
- 恢复器将失联任务转为 `retry_wait` 或 `failed`；
- 默认最多 3 次任务级尝试，指数退避并加抖动；
- 参数错误、数据明确不存在、Schema 永久不兼容不重试；
- HTTP 429、5xx、网络超时和进程失联可重试；
- analyst 级重试与任务级重试分别记录，防止无限重试。

### 3.4 阶段进度

报告保存 `stage` 和 `progress`，阶段包括：

```text
queued / fetching_data / running_analysts / assessing_risk /
synthesizing / finalizing
```

`progress` 由已完成步骤计算，不伪造线性百分比。前端显示阶段和完成的 analyst 数量。

---

## 4. 数据库模型

`users.id` 在当前项目中是 UUID，因此外键必须使用 UUID。

```sql
CREATE TABLE deep_analysis_reports (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    market              VARCHAR(4) NOT NULL CHECK (market IN ('A', 'HK', 'US')),
    ticker              VARCHAR(32) NOT NULL,
    normalized_ticker   VARCHAR(32) NOT NULL,
    analysis_version    VARCHAR(64) NOT NULL,

    status              VARCHAR(16) NOT NULL,
    stage               VARCHAR(32) NOT NULL DEFAULT 'queued',
    progress            SMALLINT NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    attempt_count       SMALLINT NOT NULL DEFAULT 0,
    max_attempts        SMALLINT NOT NULL DEFAULT 3,
    worker_id           VARCHAR(128),
    claim_token         UUID,
    lease_version       INTEGER NOT NULL DEFAULT 0,
    heartbeat_at        TIMESTAMPTZ,
    next_retry_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    idempotency_key     VARCHAR(128),
    request_fingerprint VARCHAR(64),

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    cancelled_at        TIMESTAMPTZ,
    deleted_at          TIMESTAMPTZ,
    deleted_by          UUID REFERENCES users(id) ON DELETE SET NULL,

    conclusion_status   VARCHAR(24),
    result              JSONB,
    data_snapshot       JSONB,
    error_code          VARCHAR(64),
    error_message       TEXT,
    error_detail        JSONB,

    credit_state        VARCHAR(16) NOT NULL DEFAULT 'reserved',
    reserved_credits    INTEGER NOT NULL DEFAULT 0,
    settled_credits     INTEGER NOT NULL DEFAULT 0,

    CHECK ((status = 'completed') = (result IS NOT NULL))
);

CREATE INDEX ix_deep_analysis_owner_history
    ON deep_analysis_reports (user_id, created_at DESC);

CREATE INDEX ix_deep_analysis_worker_claim
    ON deep_analysis_reports (next_retry_at, created_at)
    WHERE status IN ('pending', 'retry_wait');

CREATE INDEX ix_deep_analysis_stale_running
    ON deep_analysis_reports (heartbeat_at)
    WHERE status = 'running';

CREATE UNIQUE INDEX uq_deep_analysis_active_request
    ON deep_analysis_reports (
        user_id, market, normalized_ticker, analysis_version
    )
    WHERE status IN ('pending', 'running', 'retry_wait') AND deleted_at IS NULL;

CREATE UNIQUE INDEX uq_deep_analysis_idempotency
    ON deep_analysis_reports (user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
```

### 4.1 执行租约与提交隔离

任务队列采用 **at-least-once execution、at-most-once commit**：外部请求可能因失联恢复被重复调用，但只有当前租约持有者可以推进状态、提交结果或结算积分。

每次认领生成新的 `claim_token` 并递增 `lease_version`。以下所有写操作都必须包含：

```sql
WHERE id = :report_id
  AND status = 'running'
  AND claim_token = :claim_token
  AND lease_version = :lease_version
```

包括心跳、阶段进度、完成、失败、取消确认和积分结算。恢复器撤销旧租约后，即使旧 worker 恢复，也无法再写入。第三方 LLM 调用无法保证绝不重复，因此 provider 调用尽量携带 `report_id/analyst_id/attempt` 作为业务幂等标识，并通过 token 成本监控识别重复调用。

### 4.2 Idempotency-Key 语义

- key 作用域是当前用户，长度 1–128，只允许可打印 ASCII；
- `request_fingerprint = SHA-256(market + normalized_ticker + analysis_version)`；
- 相同 key、相同 fingerprint 重放时返回原报告；
- 相同 key、不同 fingerprint 返回 409；
- key 与报告记录共同保留，不因软删除立即复用；
- 不提供 key 时，活跃任务唯一索引仍负责业务去重；
- API 在唯一约束冲突后重新读取既有记录，不把冲突当 500。

### 4.3 软删除语义

`DELETE` 仅为终态报告设置 `deleted_at/deleted_by`。GET 和历史列表默认过滤软删除；软删除报告不参与完成缓存，但活跃任务不能删除，只能先取消。后台保留任务按策略清理 `result/data_snapshot`，账务流水和最小审计元数据继续保留。

### 4.4 缓存身份

完成报告缓存键为：

```text
user_id + market + normalized_ticker + analysis_version
```

其中 `analysis_version` 是以下内容的稳定哈希或显式版本：

- analyst 注册表和权重；
- prompt 版本；
- 数据契约版本；
- analyst/portfolio 实际模型 ID；
- risk 算法版本。

启动时由以上输入计算版本指纹，`DEEP_ANALYSIS_ANALYSIS_VERSION` 只作为可读发布标签，不能单独决定缓存。任何组成项变化都会强制新建。只有 `deleted_at IS NULL` 且完成时间在 4 小时内的报告允许缓存命中。

### 4.5 所有权约束

所有单报告查询、删除和取消必须按以下条件查询：

```text
report.id = :id AND report.user_id = current_user.id
```

未命中统一返回 404，不暴露其他用户是否拥有该报告。

---

## 5. 标的规范化与跨市场数据契约

### 5.1 标的规范化

| 市场 | 用户输入示例 | normalized_ticker |
|---|---|---|
| A | `600519`、`SH600519` | `600519.SH` |
| HK | `700`、`00700` | `0700.HK` |
| US | `aapl`、`AAPL` | `AAPL` |

规范化前必须校验格式，并通过市场元数据接口确认标的存在。用户提供的 `market` 与代码不匹配时返回 422，不静默猜测。

### 5.2 统一证据字段

```python
class EvidenceValue(BaseModel):
    evidence_id: str
    metric: str
    raw_value: float | str | None
    raw_currency: str | None
    raw_unit: str | None
    normalized_value: float | str | None
    normalized_currency: str | None
    normalized_unit: str | None
    period_type: Literal["instant", "quarter", "annual", "ttm", "daily"]
    period_end: date | None
    published_at: datetime | None
    source: str
    source_url: str | None
    source_field: str | None
    fetched_at: datetime
    quality: Literal["verified", "derived", "estimated", "missing"]
    parent_evidence_ids: list[str] = []
    formula: str | None = None
    fx_evidence_id: str | None = None
    revision: str | None = None
    missing_reason: str | None = None

class MarketData(BaseModel):
    schema_version: str
    ticker: str
    normalized_ticker: str
    company_name: str
    market: Literal["A", "HK", "US"]
    exchange: str
    industry: str | None
    reporting_currency: str
    price_currency: str
    timezone: str
    trading_calendar: str
    price_adjustment: Literal["raw", "forward", "backward"]
    as_of: datetime
    evidence_catalog: dict[str, EvidenceValue]
    price_evidence_ids: list[str]
    metric_evidence_ids: dict[str, str]
    statement_evidence_ids: dict[str, list[str]]
    news_evidence_ids: list[str]
    warnings: list[DataWarning]
```

必须区分财报期间结束日和发布日期，防止将当时尚未公开的数据用于历史分析。所有金额标准化但保留原始值、原币种和换算来源。

### 5.3 必需字段与降级

每个 analyst 在注册表声明：

- `required_fields`
- `optional_fields`
- `minimum_periods`
- `supports_markets`
- `timeout_seconds`

缺少必需字段时，该 analyst 返回 `unavailable`，不能返回伪造的 `neutral`。缺少可选字段时可返回 `degraded`，但必须列出缺失项并按规则降低置信度。

### 5.4 数据源策略

首期候选：

| 数据 | A 股 | 港股 | 美股 |
|---|---|---|---|
| 行情 | akshare | akshare，经契约测试确认具体接口 | yfinance |
| 财报 | akshare | 经 spike 验证后锁定数据源 | yfinance |
| 公司元数据 | akshare | 经 spike 验证 | yfinance |
| 新闻 | D-sight `NewsItem` + 可选 Web 搜索 | 同左 | 同左 |

港股适配在正式开发前必须完成一次数据源 spike，锁定具体函数、字段、频率、单位和失败样例。若免费源不能满足最低字段覆盖，不以猜测或错误映射补齐；该 analyst 标为不可用，或将港股基本面能力标记为 Beta。

所有第三方数据源需确认服务条款、缓存和展示权限。`ai-hedge-fund` 源码在移植前需核验许可证；不满足时只重写方法论，不复制源码或 prompt。

---

## 6. Analyst 与信号契约

### 6.1 方法论而非人物模拟

内部稳定 ID 可保留来源映射，例如 `warren_buffett`，用户界面优先展示“护城河价值”“安全边际”等方法论名称，并注明“受某投资方法启发，不代表本人观点”。这样减少误导，也便于未来调整方法而不绑定人格角色。

### 6.2 输出 Schema

```python
class AnalystSignal(BaseModel):
    analyst_id: str
    status: Literal["success", "degraded", "unavailable", "failed"]
    signal: Literal["bullish", "bearish", "neutral"] | None
    confidence: int | None = Field(default=None, ge=0, le=100)
    reasoning: str | None
    evidence_ids: list[str]
    missing_fields: list[str]
    warnings: list[str]
    model: str | None
    prompt_version: str
    duration_ms: int
    token_usage: TokenUsage | None
```

LLM 原始输出不得直接写入最终报告。必须依次通过：

1. JSON/structured output 解析；
2. Pydantic Schema 校验；
3. 枚举和数值范围校验；
4. `evidence_ids` 引用存在性校验；
5. 长度和危险内容过滤；
6. 失败后一次格式修复重试，仍失败则标记 `failed`。

analyst 只接收预计算指标和证据摘要，不负责数学计算。估值、增长率、技术指标和评分均由确定性 Python 函数计算。

### 6.3 并发与局部失败

- analyst 并发由全局 semaphore 控制，默认 8；
- 每个 analyst 独立超时，默认 45 秒；
- 使用 `gather(..., return_exceptions=True)` 或等价任务组收集局部失败；
- 一个 analyst 失败不取消其他 analyst；
- 记录每个 analyst 的状态、耗时、token 和错误码；
- 不得把 `unavailable/failed` 计入 bullish、bearish 或 neutral 数量。

### 6.4 最低覆盖门槛

输出正式结论必须同时满足：

- `fundamentals` 或至少一个核心价值 analyst 成功；
- `technical` 成功；
- 至少 8 个 analyst 为 `success/degraded`；
- 必需财务数据覆盖率达到配置阈值；
- 数据新鲜度符合对应市场规则。

不满足时，报告状态仍可为 `completed`，但结论状态为 `insufficient_data`，只展示已有信号和缺失原因，不给出买入/卖出结论。

### 6.5 防止“多数投票即真相”

13 个投资方法高度相关，不能按人头等权投票。registry 将 analyst 归入价值、成长、宏观、技术、基本面等方法簇；portfolio manager 接收方法簇聚合结果、数据质量和冲突度，而不是简单的 `9/15` 多数票。报告仍可展示计数，但结论不得仅以计数为依据。

---

## 7. 风险引擎与最终结论

### 7.1 风险引擎

首期只有单标的输入，因此不声称计算用户真实仓位上限，也不使用“相关性矩阵”。确定性风险引擎输出：

```python
class RiskAssessment(BaseModel):
    level: Literal["low", "medium", "high", "very_high", "unknown"]
    volatility_percentile: float | None
    max_drawdown_90d: float | None
    liquidity_warning: bool
    data_quality: str
    reference_risk_budget_pct: float | None
    methodology_version: str
```

`reference_risk_budget_pct` 仅是基于波动率的参考风险预算，界面必须注明它不是个性化仓位建议。真实 `position_limit_pct` 留待未来接入用户组合、资金和风险偏好后实现。

### 7.2 Portfolio manager 输入约束

portfolio manager 只接收：

- 通过校验的 analyst 信号；
- 方法簇聚合结果和分歧程度；
- risk engine 输出；
- 数据质量和缺失摘要；
-允许的结论枚举。

输出：

```python
class Conclusion(BaseModel):
    status: Literal["actionable", "insufficient_data"]
    action: Literal["buy", "hold", "sell"] | None
    confidence: int | None
    reasoning: str
    supporting_analysts: list[str]
    opposing_analysts: list[str]
    key_risks: list[str]
    evidence_ids: list[str]
```

程序独立重算计数和覆盖率，LLM 无权修改 analyst 原始信号、数据、计数、风险数值或最低覆盖门槛。

---

## 8. LLM 配置与调用复用

新增配置：

```text
DEEP_ANALYSIS_ANALYST_MODEL=deepseek-v4-flash
DEEP_ANALYSIS_PORTFOLIO_MODEL=deepseek-v4-pro
DEEP_ANALYSIS_MAX_CONCURRENCY=8
DEEP_ANALYSIS_ANALYST_TIMEOUT_SECONDS=45
DEEP_ANALYSIS_TASK_TIMEOUT_SECONDS=300
DEEP_ANALYSIS_MAX_ATTEMPTS=3
DEEP_ANALYSIS_CACHE_HOURS=4
DEEP_ANALYSIS_CREDITS=50
DEEP_ANALYSIS_WORKER_ENABLED=false
DEEP_ANALYSIS_ANALYSIS_VERSION=v1
```

当前 `app.agent.build._make_model()` 只读取单一模型配置。实施时应提取可复用的模型构造器，例如 `make_deepseek_model(model_name, timeout)`，继续使用现有白名单和 `ContentRiskRetryChatModel`，避免 Chat 与深度分析形成两套重试和安全行为。

每次报告必须记录实际模型 ID、prompt 版本、token 使用量和运行参数。配置缺失时服务启动失败或功能明确关闭，不能静默回退到错误模型。

---

## 9. API 与 Chat 集成

### 9.1 REST API

| 方法 | 路径 | 行为 |
|---|---|---|
| POST | `/api/deep-analysis` | 原子检查缓存/活跃任务/积分并创建报告，立即返回 |
| GET | `/api/deep-analysis/{id}` | 查询本人报告状态、进度和结果 |
| GET | `/api/deep-analysis` | 本人历史，支持 ticker/market/status/cursor 过滤 |
| POST | `/api/deep-analysis/{id}/cancel` | 取消 pending/running 任务 |
| DELETE | `/api/deep-analysis/{id}` | 软删除本人已结束报告，不终止运行任务 |

POST 返回：

```json
{
  "id": "uuid",
  "status": "pending",
  "cache_hit": false,
  "deduplicated": false,
  "reserved_credits": 50
}
```

要求：

- ticker 规范化失败返回 422；
- 积分不足返回 402；
- 同一活跃请求返回已有 id，`deduplicated=true`；
- 命中完成缓存返回已有 id，`cache_hit=true`；
- 创建接口接受可选 `Idempotency-Key`；
- 历史列表使用 cursor 分页，限制单页数量；
- `error_detail`、内部 prompt 和 provider 原始错误不返回前端。

### 9.2 Chat 工具

为了真正不阻塞 Chat，拆成两个工具：

```python
@tool
async def start_deep_analysis(ticker: str, market: str) -> str:
    """启动深度分析并立即返回报告 ID、状态和查看方式。缓存命中时可返回摘要。"""

@tool
async def get_deep_analysis(report_id: str) -> str:
    """查询当前用户的深度分析报告；完成时返回 500 token 内摘要。"""
```

新任务不得在 Chat tool call 内等待 90 秒。Agent system prompt 明确：启动后告知用户任务在后台运行；只有用户追问或缓存命中时查询结果。

工具通过闭包绑定 `user_id` 和 sessionmaker，不能接受客户端传入用户 ID。报告链接使用前端内部面板定位，不暴露可猜测的跨用户资源。

---

## 10. 积分与事务语义

### 10.1 计费规则

- 完成缓存命中：不扣费；
- 活跃任务去重：不重复扣费；
- 创建新任务：预留固定积分；
- 成功完成或 `insufficient_data` 且已交付有效报告：结算；
- 系统错误、数据源完全不可用、模型服务失败：全额释放；
- 用户在任务开始前取消：全额释放；
- 用户在任务运行后取消：首期全额释放，后续可根据真实成本调整；
- 管理员是否免扣沿用现有 credits 规则。

### 10.2 原子创建

创建报告与积分预留在同一数据库事务中：

1. 锁定 `CreditAccount`；
2. 再次检查完成缓存和活跃任务；
3. 校验余额；
4. 创建 report；
5. 写入唯一 `CreditTransaction`，`ref_type=deep_analysis`、`ref_id=report_id`；
6. 提交。

不得使用”先 precheck、稍后 charge”的分离流程。积分交易需具备幂等约束，任何重试都不能重复预留、结算或退款。

### 10.3 积分账务模型扩展

当前 `CreditTransaction` 无幂等约束，需增加以下字段和约束以支持深度分析计费：

```sql
ALTER TABLE credit_transactions
ADD COLUMN operation VARCHAR(16);  -- reserve / settle / release

CREATE UNIQUE INDEX uq_credit_tx_deep_analysis
ON credit_transactions (ref_type, ref_id, operation)
WHERE ref_type = 'deep_analysis';
```

**账务不变量：**

- 预留（reserve）：立即从 `balance` 扣除，不使用单独 `reserved_balance`；`amount < 0`；
- 结算（settle）：补扣差额或原地确认；深度分析首期固定价格，差额为 0；`amount <= 0`；
- 释放（release）：退回预留；`amount > 0`；
- 每个 `report_id` 只能有一次 reserve、一次 settle 或一次 release，由唯一索引保证；
- 月度 reset 不受预留影响：未结预留在下月初仍计入 `balance`，reset 直接置为 `monthly_quota`；
- 管理员创建报告时：`credit_state=exempt`，不写预留流水，不影响余额。

**状态转换：**

```
reserve → settle (成功完成)
reserve → release (失败、取消、系统错误)
```

settle 和 release 均需原子校验 `credit_state=reserved` 且 `claim_token` 有效；worker 完成时必须在同一事务内提交结果和结算积分。

---

## 11. 报告结构

```json
{
  "schema_version": "1",
  "analysis_version": "v1",
  "ticker": "600519",
  "normalized_ticker": "600519.SH",
  "company_name": "贵州茅台",
  "market": "A",
  "generated_at": "2026-07-28T10:00:00Z",
  "data_as_of": "2026-07-28T07:00:00Z",
  "data_quality": {
    "status": "good",
    "coverage_pct": 92,
    "warnings": []
  },
  "analyst_signals": {
    "moat_value": {
      "status": "success",
      "signal": "bullish",
      "confidence": 82,
      "reasoning": "护城河指标稳定，估值仍有正安全边际",
      "evidence_ids": ["roe_ttm", "fcf_ttm", "margin_of_safety"],
      "missing_fields": [],
      "warnings": []
    }
  },
  "analyst_summary": {
    "success": 11,
    "degraded": 2,
    "unavailable": 1,
    "failed": 1,
    "bullish": 8,
    "bearish": 2,
    "neutral": 3,
    "cluster_disagreement": 0.34
  },
  "risk": {
    "level": "medium",
    "volatility_percentile": 42,
    "max_drawdown_90d": -12.4,
    "reference_risk_budget_pct": 8.5,
    "methodology_version": "risk-v1"
  },
  "conclusion": {
    "status": "actionable",
    "action": "buy",
    "confidence": 74,
    "reasoning": "价值和基本面方法簇偏多，技术面短期承压",
    "supporting_analysts": ["moat_value", "fundamentals"],
    "opposing_analysts": ["technical"],
    "key_risks": ["短期趋势走弱"],
    "evidence_ids": ["roe_ttm", "fcf_ttm", "trend_60d"]
  },
  "provenance": {
    "models": {},
    "prompt_versions": {},
    "data_sources": [],
    "token_usage": {},
    "duration_ms": 48321
  }
}
```

`data_snapshot` 可保存用于审计的标准化数值，但新闻正文、第三方受限内容和不必要的 provider 原始响应不得全量落库。定义保留周期与清理策略。

---

## 12. 前端面板

`frontend/src/panels/DeepAnalysis/` 包含：

- 标的输入、市场选择与规范化反馈；
- 当前阶段、已完成 analyst 数和取消操作；
- 顶部结论、置信度、数据质量和时间戳；
- 按方法簇组织的 analyst 卡片；
- `success/degraded/unavailable/failed` 明确状态；
- 证据抽屉：关键数字、来源、报告期、币种与抓取时间；
- 风险信息和“非个性化仓位建议”提示；
- 历史报告、缓存命中标识和分析版本；
- 失败后的可理解错误与安全重试入口。

信号颜色不能作为唯一信息载体，需同时提供图标和文本。页面必须展示“仅供研究参考，不构成投资建议”。

轮询策略：运行时 3 秒，连续空闲后逐步退避；页面隐藏时降低频率；进入终态后停止。后续任务量增加时可升级为 SSE，但首期不需要。

---

## 13. 安全、隐私与合规

- 所有 API 均要求认证，并校验报告所有权；
- ticker、market、分页参数和 Idempotency-Key 严格校验；
- 第三方新闻和网页内容视为不可信数据，不能进入 system prompt；
- analyst prompt 明确忽略数据中的指令文本，防止 prompt injection；
- 面向前端的 reasoning 经过长度限制和文本安全处理；
- 日志不记录 API key、完整 prompt、新闻全文或用户敏感信息；
- 数据快照设置保留期，软删除后由后台清理；
- 核验数据源和上游仓库许可证、缓存、再分发及署名要求；
- UI 不声称真实投资者参与、背书或给出本人观点；
- 不提供自动执行交易的接口。

---

## 14. 可观测性

### 14.1 指标

- 任务排队时长、总耗时和各阶段耗时；
- pending/running/retry_wait/failed 数量；
- stale running 恢复次数；
- 各市场数据字段覆盖率和数据源失败率；
- 各 analyst 成功、降级、超时和非法输出率；
- LLM token、成本、429 和 5xx；
- 缓存命中率、活跃任务去重率；
- 积分预留、结算和释放数量；
- P50/P95/P99 完成时间。

### 14.2 结构化日志

每条日志至少包含：

```text
report_id, user_id_hash, market, normalized_ticker,
analysis_version, worker_id, stage, attempt_count, error_code
```

不得记录完整用户 ID、API key、原始财报或完整 LLM 输入输出。

### 14.3 告警

首期至少对以下情况告警：

- stale running 数量持续增加；
- 失败率或数据源错误率超过阈值；
- 积分处于 `reserved` 超过最长任务时间；
- worker 无心跳；
- 单报告 token 或耗时异常；
- 某市场数据覆盖率显著下降。

---

## 15. 测试与评估

### 15.1 单元测试

- 三市场 ticker 规范化和非法输入；
- 币种、单位、期间和发布日期标准化；
- 每个确定性财务/技术指标；
- analyst 输出 Schema、证据引用和置信度范围；
- risk 算法边界值；
- 计费状态机和退款幂等；
- 报告状态机的合法/非法转换。

### 15.2 数据契约测试

每个市场至少选择 3 个固定标的，覆盖正常、字段缺失和异常单位。保存脱敏 fixture，CI 不依赖外网。定期在非 CI 环境运行 live contract test，发现上游字段漂移。

### 15.3 集成测试

使用 PostgreSQL 测试容器验证：

- 两个 worker 只认领一次；
- API/worker 重启后恢复；
- 同时触发时只创建一个活跃任务；
- 缓存严格区分 market 和 analysis_version；
- 越权读取、取消和删除返回 404；
- 单 analyst 失败不导致整份报告失败；
- 覆盖不足产生 `insufficient_data`；
- 预留、结算、释放均只执行一次；
- provider 429、超时和非法 JSON 的重试边界。

### 15.4 前端测试

- pending/running/completed/failed/cancelled 全状态；
- unavailable/degraded analyst 展示；
- 轮询停止、退避和卸载清理；
- 无颜色也可辨别信号；
- 数据证据和免责声明可访问。

### 15.5 准确性评估

建立带时间截面的固定评估集，禁止使用当时未公开财报。至少比较：

1. 当前 D-sight 单 Agent 基线；
2. 纯确定性指标基线；
3. 多方法论系统。

指标包括：方向准确率、Brier score/置信度校准、人工证据一致性评分、稳定性、覆盖率、成本和延迟。只有多方法论系统在证据一致性与至少一个业务指标上显著优于基线，才移除 Beta 标识。

---

## 16. 部署与运维

### 16.1 进程模型

API 和 worker 使用同一代码镜像，通过启动命令区分：

```bash
# API 进程（现有 uvicorn）
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Worker 进程
python -m app.deep_analysis.worker
```

Worker 启动检查：

- 必需配置全部存在且有效（模型 key、模型 ID、并发、超时、积分价格）；
- 数据库连接可用且迁移版本匹配；
- `DEEP_ANALYSIS_WORKER_ENABLED=true` 明确开启；
- 缺少任一项拒绝启动，不能静默降级或跳过。

API 进程可以在 feature flag 关闭时启动；worker 配置不足时 API 返回 503 并提示功能关闭。

### 16.2 Worker 架构

```python
# app/deep_analysis/worker.py 伪代码
async def main():
    async with db_engine.begin() as conn:
        await acquire_advisory_lock(conn, "deep_analysis_maintenance")
    
    tasks = [
        asyncio.create_task(claim_loop()),
        asyncio.create_task(maintenance_loop()),
    ]
    
    shutdown_event = asyncio.Event()
    signal.signal(signal.SIGTERM, lambda: shutdown_event.set())
    
    await shutdown_event.wait()
    # 停止认领新任务
    stop_claiming.set()
    # 等待当前任务或超时
    await asyncio.wait(tasks, timeout=grace_period)

async def claim_loop():
    while not stop_claiming.is_set():
        report_id = await claim_one()
        if report_id:
            asyncio.create_task(execute_report(report_id))
        else:
            await asyncio.sleep(2)

async def maintenance_loop():
    while not stop_claiming.is_set():
        await recover_stale()
        await transition_retry_wait()
        await release_expired_credits()
        await asyncio.sleep(30)

async def execute_report(report_id):
    token = current_claim_token
    async def heartbeat():
        while True:
            await update_heartbeat(report_id, token)
            await asyncio.sleep(15)
    
    hb_task = asyncio.create_task(heartbeat())
    try:
        # 数据获取、analyst fan-out、风险、汇总
        await runner.run(report_id, token)
    finally:
        hb_task.cancel()
```

**关键约束：**

- 心跳协程与主任务解耦，心跳失败不中断主任务；
- akshare/yfinance 阻塞调用使用 `asyncio.to_thread` 或独立进程池；
- 数据库不可用时，当前任务按不可恢复错误失败并优雅退出，不无限重试连接；
- 维护 loop 通过 PostgreSQL advisory lock 保证单实例；
- SIGTERM 触发优雅关闭：停止认领，当前任务最多等待 grace period（默认 120 秒），超时强制退出。

### 16.3 部署顺序与回滚

**正向部署：**

1. 运行 Alembic migration；
2. 启动 worker（旧版 API 继续运行，新表无影响）；
3. 部署新 API 并打开 feature flag；
4. 观察指标；必要时关闭 flag，不需回滚代码。

**回滚：**

- 关闭 feature flag 或回滚 API；
- worker 可继续完成已触发报告；
- 不删除表或数据；旧 `analysis_version` 报告仍可通过 GET 读取；
- 迁移支持 expand/contract 模式：新字段允许 NULL，旧版本可运行。

### 16.4 数据库连接与并发容量

当前 `get_sessionmaker()` 使用默认连接池（通常 5–10）。深度分析增加：

- API 创建事务：瞬时峰值；
- worker claim/heartbeat/progress：持续占用；
- LangGraph checkpointer：Chat 使用；
- 后台任务（news/social/fund_arb）：现有消耗。

建议为 worker 使用独立 sessionmaker 并设置专用连接池，或增加全局连接池容量至 20–30。每个 worker 最多占用 `1 + max_concurrency`（1 个心跳连接 + N 个并发任务的短事务）。

### 16.5 监控与告警实施

首期使用 FastAPI `/metrics`（Prometheus 格式）+ 结构化 JSON 日志：

- worker 暴露独立 health/metrics 端点（HTTP 8001）；
- 指标通过 `prometheus_client` 库导出；
- 告警通过现有监控栈（若无，先用日志 + 定期扫描脚本）。

必须实施的告警（阈值待定稿）：

- `deep_analysis_stale_running > 5`（5 分钟窗口）；
- `deep_analysis_failure_rate > 0.3`（30 分钟窗口）；
- `deep_analysis_credits_reserved_hours > 6`（任一报告预留超过 6 小时）；
- `deep_analysis_worker_heartbeat_age_seconds > 120`；
- `deep_analysis_p95_duration_seconds > 600`（P95 完成时间超过 10 分钟）。

---

## 17. 实施分期

### Phase 0：数据与许可证 spike

- 核验 `ai-hedge-fund` 许可证和可复用边界；
- 锁定 A/HK/US 的具体数据接口与字段映射；
- 为每个市场完成 3 个标的数据契约样例；
- 验证 DeepSeek 模型 ID、结构化输出和并发限额；
- 输出 go/no-go 结论，不开发前端。

### Phase 1：可靠任务骨架

- ORM、Alembic migration、状态机和 PostgreSQL worker；
- 任务认领、心跳、恢复、取消和幂等；
- 积分预留/结算/释放事务；
- API 仅返回模拟 runner 结果，先验证可靠性。

### Phase 2：A 股分析闭环

- 完成统一数据契约和 A 股 adapter；
- 先实现 fundamentals、technical 和 3 个互补方法论；
- risk engine 与 portfolio manager；
- 通过最低覆盖、证据链和基线评估后再扩充 analyst。

### Phase 3：双入口

- 面板全状态和历史报告；
- `start_deep_analysis`、`get_deep_analysis` Chat 工具；
- 来源、数据质量、免责声明和错误展示。

### Phase 4：方法论与市场扩展

- 扩展至全部经验证的方法论；
- 港股 adapter 达到最低字段覆盖后开放；
- 美股 adapter 达到最低字段覆盖后开放；
- 每个市场单独通过评估门槛，不因 A 股通过而默认放行。

### Phase 5：生产灰度

- feature flag 仅对管理员/小比例用户开放；
- 观察失败率、数据覆盖、token、延迟和计费一致性；
- 通过验收门槛后逐步放量。

---

## 18. 生产验收门槛

上线前必须全部满足：

- [ ] 三市场各自的数据契约测试通过；
- [ ] 用户 UUID 外键、所有权和越权测试通过；
- [ ] 多 worker 无重复执行，重启后任务可恢复；
- [ ] 缓存键包含 market 和 analysis_version；
- [ ] 计费在并发、重试和失败下保持幂等；
- [ ] LLM 输出全部经过 Schema 和证据引用校验；
- [ ] 数据不足时不输出误导性投资动作；
- [ ] Chat 新任务触发立即返回，不等待完整分析；
- [ ] P95 完成时长、失败率和 token 成本达到配置目标；
- [ ] 许可证、数据条款和免责声明审核完成；
- [ ] 固定评估集上不劣于当前单 Agent 基线；
- [ ] 告警、恢复任务和运维 runbook 已验证。

---

## 19. 待最终确认的产品参数

这些参数不阻塞架构，但应在实施计划前定稿：

1. 固定积分价格是否采用 50 credits；
2. 报告保留期和数据快照保留期；
3. Beta 阶段开放人群；
4. 港股免费数据源达不到最低覆盖时，是暂缓开放还是允许降级版；
5. UI 是否展示投资者姓名，还是只展示方法论名称。
