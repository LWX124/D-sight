# D-sight 股票诊断设计计划

状态：规划完成，尚未实施。

## 1. 结论

D-sight 不应该照搬 `daily_stock_analysis` 的页面、模块数量或多 Agent 数量。真正值得借鉴的是它已经形成的闭环：统一分析上下文、结构化决策、风险护栏、历史比较、主动提醒、后验评估和数据源可观测性。

当前最短路径不是再增加一个股票分析 Skill，而是把已有 `deep_analysis` 可靠任务骨架升级为“诊断档案 + 不可变诊断版本 + 多轮问答 + 后验复盘”的一等产品能力。

首个完整闭环以 A 股和美股为主，港股随后，日本股票和韩国股票最后扩展。不同市场共享契约，不强求字段一致；不支持的市场特有数据必须显式标记 `not_supported`，不能用其他市场概念替代。

## 2. 源码审查结论

### 2.1 D-sight 已有的可复用基础

1. `backend/app/deep_analysis/` 已有持久化任务、租约、心跳、重试、取消、幂等、缓存、积分预留与释放机制。这部分比参考项目的普通后台任务更适合作为生产任务底座。
2. `backend/app/chat/`、`backend/app/threads/` 和 LangGraph checkpointer 已支持持久化多轮会话。
3. Skill Router、知识库、新闻、社媒和 Web 搜索已经可以为诊断提供外部材料。
4. 股票研究 Skill 已覆盖价值研究、财务、管理层、组合复盘、投资论文、论文漂移、股东结构、事件风险与选股等方法论。
5. 现有认证、所有权校验、积分系统和前端 Chat 壳可以复用，不需要另建账号或计费体系。

### 2.2 当前真实缺口

1. `backend/app/deep_analysis/runner.py` 明确是 Mock Runner，只推进阶段并写固定 `hold` 结果，没有真实取数、分析、冲突复核或风险判断。
2. `DeepAnalysisStatusResponse.result` 仍是无约束 `dict[str, Any]`；没有版本化证据、分周期结论、七态动作或数据质量门禁。
3. 现有 `DeepAnalysisReport` 同时承担运行任务和最终报告，无法自然表达“一个诊断档案拥有多个不可变版本”。
4. 前端只有 `/chat` 主路由，没有诊断档案、版本历史、证据抽屉、更新提醒或后验结果页面。
5. 当前内置股票工具 `stock_quote`、`stock_financials` 实际只覆盖 A 股，和旧设计中 A/H/US 的接口声明不一致。
6. 多项 QuantSkills Skill 声明依赖 `pandadata-api`、`references/` 和 `scripts/`，但仓库只保存并物化 `SKILL.md`。例如 `skill-a-share-stock-dossier` 的执行依赖在当前运行工作区并不闭合。
7. Skill 输出以 Markdown 和工作区文件为主，缺少统一机器契约，无法稳定进入版本比较、风险门禁和后验评估。
8. 当前聊天会话没有诊断档案或诊断版本引用；模型可能在后续问答中重新取数或改变口径，无法回答结论变化来自哪里。

### 2.3 参考项目最值得借鉴的能力

| 参考能力 | 借鉴价值 | D-sight 落地方式 | 优先级 |
|---|---|---|---|
| `AnalysisContextPack` | 统一输入、来源、时点、缺失和降级状态 | 建立版本化 `EvidencePack`，成为所有分析维度唯一输入 | P0 |
| 数据质量评分与限制 | 阻止低质量输入产生积极动作 | 改为按市场、周期配置必需证据；质量可否决动作 | P0 |
| 结构化报告 Schema | 防止 Markdown 成为唯一真源 | 诊断版本保存结构化结果，Markdown 只做渲染 | P0 |
| DecisionSignal 生命周期 | 让建议可查询、比较和复盘 | 采用七态诊断动作、周期、触发与失效条件 | P0 |
| 风险 guardrail | 模型不能绕过硬风险 | 使用确定性风险与价格关系规则降级动作 | P0 |
| Agent disagreement explanation | 解释不同维度为何冲突 | 只在实质冲突时复核，持久化最终决策路径 | P1 |
| 历史信号比较 | 看清观点迁移 | 诊断版本 diff 区分事实、价格、规则与画像变化 | P1 |
| 数据源 fallback/health | 免费源波动时仍可解释 | Provider Registry、last-good cache、source health | P1 |
| 主动告警 | 让诊断持续有效 | 生成更新提醒，用户确认后才创建新版本 | P2 |
| Outcome/反馈统计 | 形成可验证闭环 | 分市场、周期、动作、质量统计后验结果 | P2 |
| Skill outcome 权重 | 用表现校准维度贡献 | 只生成调权建议，不在线自动改权 | P3 |
| 选股引擎 | 为诊断提供候选入口 | 独立于诊断核心，候选可一键创建诊断档案 | P3 |
| 组合风险与持仓告警 | 让建议理解持仓背景 | 首期只读取最小持仓上下文，不做完整组合优化 | P3 |

### 2.4 不建议直接照搬的部分

1. 不使用单一“情绪分”平均短期交易与长期投资判断。
2. 不让所有 Agent 每次完整辩论；只对真实冲突做定向复核。
3. 不让 LLM 计算财务指标、技术指标、价格关系或风险阈值。
4. 不把 A 股的筹码、北向资金、龙虎榜等概念套用到美股、港股或日韩市场。
5. 不把选股、诊断、告警和组合管理合并成一个巨型首期版本。
6. 不复制参考项目代码；只吸收概念和契约。任何代码或数据源复用必须先核验 MIT、Apache、GPL 及数据再分发条款。

## 3. 产品范围

### 3.1 目标

1. 用户可为一只股票创建长期存在的诊断档案。
2. 每次创建或显式更新生成不可变诊断版本。
3. 诊断按短期、中期、长期分别形成判断，由决策画像中的主周期决定最终建议。
4. 同一证据层保持一致；持仓状态、主周期和风险偏好只影响决策解释层。
5. 用户可以围绕指定诊断版本进行多轮问答，问答不会隐式改写版本。
6. 系统主动发现新财报、重大事件、失效条件和数据过期，生成更新提醒。
7. 每个建议都能追溯证据、数据时点、模型/规则版本和风险调整路径。
8. 系统记录后验结果，用于评估和校准，不在线自动学习。

### 3.2 非目标

1. 自动下单、账户托管或交易执行。
2. 完整组合优化、税务、现金流和相关性矩阵。
3. 高频、分钟级或日内自动交易信号。
4. 所有市场首期达到相同字段覆盖。
5. 用更多 Agent 数量作为准确率指标。
6. 把模型置信度包装成投资确定性。

## 4. 领域模型

```text
DiagnosisFile（诊断档案）
├── Instrument（规范化标的）
├── DiagnosisVersion[]（不可变诊断版本）
│   ├── DecisionProfileSnapshot（决策画像快照）
│   ├── EvidencePack（诊断证据）
│   ├── DimensionOpinion[]（维度意见）
│   ├── ConflictReview?（冲突复核）
│   ├── RiskAssessment（风险约束）
│   ├── DiagnosisAdvice（诊断建议）
│   └── Provenance（规则、模型、来源与成本）
├── DiagnosisConversation[]（诊断问答）
├── UpdateReminder[]（更新提醒）
└── OutcomeObservation[]（后验结果）

DiagnosisRun（可变执行任务）
└── 成功后只提交一个新的 DiagnosisVersion
```

### 4.1 关键不变量

1. `DiagnosisVersion` 创建后不可修改；修正也产生新版本并标记原因。
2. `DiagnosisRun` 是可重试的操作记录，`DiagnosisVersion` 是不可变业务事实，两者不能继续混为同一对象。
3. 普通诊断问答必须固定引用一个版本；需要新数据时只能发起显式更新。
4. 同一个版本中的所有维度共享同一份 `EvidencePack`，不得各自静默重新抓取数据。
5. 所有最终建议必须通过数据质量门禁和确定性风险约束。
6. 每个 `evidence_id` 必须能解析到真实证据项；不存在的引用使该维度意见无效。
7. `buy/add` 必须包含主周期、触发条件、失效条件和风险依据。
8. 空仓只允许 `buy/watch/avoid`；持仓只允许 `add/hold/reduce/sell`。
9. `alert` 属于更新提醒，不进入诊断动作枚举。

## 5. 核心契约

### 5.0 DecisionProfileSnapshot（决策画像快照）

创建诊断版本时冻结，同一版本中所有维度共享此画像。不同版本可以有不同的画像（用户主动调整或系统规则触发）。

```python
class PositionType(Enum):
    EMPTY = "empty"      # 空仓：允许 buy / watch / avoid
    HOLDING = "holding"  # 持仓：允许 add / hold / reduce / sell

class DecisionProfileSnapshot:
    position_status: PositionType
    primary_horizon: Literal["short", "medium", "long"]
    risk_tolerance: Literal["conservative", "moderate", "aggressive"]

    # 持仓上下文（position=HOLDING 时必需）
    portfolio_weight: float | None    # 占组合比例，0.0-1.0；holding 时必需
    target_position_weight: float | None  # 目标仓位，0.0-1.0
    cost_basis: float | None          # 持仓均价
    entry_date: date | None           # 建仓日期

    # 用户约束
    max_position_weight: float | None # 单只股票最大持仓占比，0.0-1.0
    tags: list[str]                   # 用户标签（如 "核心仓位""观察仓"）

    # 快照溯源
    changed_from: str | None          # 上一个 profile_id
    change_reason: str | None
```

关键不变量：
- 空仓画像 (`empty`) 只允许 `buy/watch/avoid`，且拒绝持仓专用字段；持仓画像 (`holding`) 必须包含 `portfolio_weight`，只允许 `add/hold/reduce/sell`。
- `risk_tolerance=conservative` 升高入场门槛（如要求更大的安全边际）。
- `target_position_weight > max_position_weight` 时输入无效；只有两个值都存在时才执行集中度校验。
- 同一档案的不同版本可以有不同的画像，但同一版本内画像不变。

### 5.1 Instrument

```python
class Instrument:
    market: Literal["CN", "US", "HK", "JP", "KR"]
    canonical_symbol: str
    exchange: str
    display_name: str | None
    currency: str
    timezone: str
    # 规范化溯源
    original_input: str | None        # 用户原始输入
    normalization_method: str | None  # 使用的规范化方法
    ambiguity_resolved: bool          # 是否已解决名称歧义
    candidates: list[str] | None      # 歧义候选列表
```

标的规范化必须由一个注册表负责，不能继续在各工具内分别猜测。原始输入与规范化结果同时保留；名称匹配需要返回候选并让用户确认歧义。`normalization_method` 记录规范化路径（如 `code_pattern` / `ticker_pattern` / `name_lookup`），便于审计和问题排查。

### 5.2 EvidencePack

证据块建议首版包含：

- `identity`
- `quote`
- `daily_bars`
- `technical`
- `fundamentals`
- `valuation`
- `events`
- `news`
- `market_context`
- `ownership`
- `capital_flow`
- `portfolio_context`

每个块和字段使用统一状态：

```text
available / partial / fallback / stale / estimated /
missing / not_supported / fetch_failed
```

每个证据项至少包含：

```python
class EvidenceItem:
    evidence_id: str
    status: EvidenceStatus
    value: JSONValue | None
    source: str | None
    source_record_id: str | None
    as_of: datetime | date | None
    fetched_at: datetime | None
    currency: str | None
    unit: str | None
    period: str | None
    fallback_from: str | None
    missing_reason: str | None
    warnings: list[str]
```

`EvidencePack` 自身不抓数据，只组装 provider 已返回的标准化结果，避免出现第二套隐藏请求链。

状态为 `not_supported` 的块和证据项不计入 `quality_score` 和 `completeness` 的分母——它们代表市场能力限制而不是数据质量缺陷。例如美股 `capital_flow` 为 `not_supported` 不应拉低美股诊断的总分。但这不改变主周期必需块的判定：若必需块本身为 `not_supported`，则该市场该周期诊断不可用。

### 5.3 诊断周期

| 周期 | 主要问题 | 典型证据 | 不应主导的证据 |
|---|---|---|---|
| 短期 | 当前是否具备执行条件 | 完整日线、量价、技术、事件、市场阶段 | 长期护城河单独决定入场 |
| 中期 | 未来一至数个财报期是否改善 | 业绩趋势、行业景气、估值、催化 | 单日波动直接改变基本面 |
| 长期 | 生意质量和价格是否匹配 | 商业质量、财务质量、治理、资本配置、长期估值 | 盘中价格改写质量判断 |

具体天数只作为后验观察参数，不进入领域语义硬编码。建议初始观察点为 5、20、60、120 个交易日，后续通过评估集调整。

### 5.4 DimensionOpinion

首期不启用 13 个角色。建议使用六个稳定维度：

1. `business_quality`：商业质量与竞争优势。
2. `financial_quality`：增长、盈利、现金流、资产负债与资本配置。
3. `valuation`：估值区间与安全边际。
4. `technical`：趋势、量价、波动和关键价格区间。
5. `events_and_sentiment`：财报、公告、新闻、催化与风险事件。
6. `market_structure`：市场阶段、行业/主题位置和宏观环境。

```python
class DimensionOpinion:
    dimension_id: str
    horizon: Literal["short", "medium", "long"]
    status: Literal["success", "degraded", "unavailable", "failed"]
    direction: Literal["bullish", "neutral", "bearish"] | None
    confidence: float | None  # 维度内部证据一致性，0.0-1.0，不表示预测准确率
    thesis: str | None
    evidence_ids: list[str]
    missing_evidence_ids: list[str]
    warnings: list[str]
    analyzer_version: str
```

方向规则：
- `status=success` 时，`direction` 必须为 `bullish/neutral/bearish` 之一，均进入决策。
- `status=degraded` 时，`direction` 可赋值但附带 `warnings`，权重降低。
- `status=unavailable|failed` 时，`direction=None`，不参与决策，不能伪装成 `neutral`。
- 冲突检测只考虑具有非空方向的 `success/degraded` 意见；`degraded` 必须包含 warning。`confidence` 表示该维度内部证据的一致性和完整性，不是方向预测准确率。

财务计算、估值区间、技术指标与风险数值先由确定性代码产生；LLM 只解释已经计算和校验的证据。

### 5.5 ConflictReview

触发条件至少包括：

- 同一周期同时出现高置信度多头与空头意见；
- 估值与质量方向相反且任一为高置信度；
- 技术执行条件与主周期建议相反；
- 新事件可能使既有核心论点失效；
- 多个维度引用同一证据却得出矛盾解释。

复核只接收冲突意见和相关证据，不重新运行全部维度。输出必须说明冲突是否解决、保留哪些异议、哪些证据仍缺失。

### 5.6 RiskAssessment 与质量门禁

质量门禁先于风险约束：

```text
EvidencePack
  -> 主周期必需证据门禁
  -> 维度意见覆盖门禁
  -> 确定性风险约束
  -> 七态动作校验
```

诊断可用性：

- `actionable`：主周期证据达到门槛，可产生条件化动作。
- `limited`：可解释，但只允许 `watch/hold/reduce/avoid` 等保守动作。
- `insufficient`：核心证据不足或矛盾无法解决，不产生投资动作。

风险规则首期至少覆盖：

- 流动性不足；
- 波动与最大回撤异常；
- 财务或审计异常；
- 重大事件未澄清；
- 数据陈旧或来源冲突；
- 入场、止损、目标价格关系不合法；
- 盘中涨幅或未完成 K 线导致的追高风险；
- 市场阶段不允许执行；
- 持仓集中度超标：若画像提供的 `target_position_weight > max_position_weight`，画像在入口即无效；执行层不得自行猜测拟增权重。

风险约束只能保持或降低积极程度，不能把保守意见升级为积极动作。

### 5.7 DiagnosisAdvice

```python
class DiagnosisAdvice:
    availability: Literal["actionable", "limited", "insufficient"]
    action: Literal["buy", "watch", "avoid", "add", "hold", "reduce", "sell"] | None
    primary_horizon: Literal["short", "medium", "long"]
    confidence: float | None
    trigger_conditions: list[str]
    invalidation_conditions: list[str]
    execution_adjustments: list[str]
    supporting_dimensions: list[str]
    opposing_dimensions: list[str]
    evidence_ids: list[str]
    decision_path: list[DecisionTransition]
```

`confidence` 表示当前证据下的分析稳定度，不表示未来收益概率。用户界面必须同时展示数据质量和反方证据，不能只展示一个百分比。

### 5.8 分析版本身份

`analysis_version` 必须由以下内容生成稳定指纹：

- EvidencePack Schema 版本；
- provider 规范化规则版本；
- 确定性指标版本；
- 维度注册表和权重版本；
- prompt 版本；
- 模型兼容契约版本；实际模型精确 ID、端点和参数独立记录在 execution provenance 中。跨 patch 复用只能依赖显式维护的兼容版本；
- 冲突检测规则版本；
- 数据质量门槛版本；
- 风险规则版本；
- 动作映射规则版本。

`analysis_version` 只标识方法契约，不混入 evidence/profile 内容。结果或缓存键显式组合 `analysis_version + evidence_hash + profile_hash + freshness_policy`。Evidence hash 覆盖全部语义字段，排除易变的抓取时间；freshness 单独判断。

## 6. 市场能力设计

### 6.1 市场优先级

1. 第一阶段：A 股、美股。
2. 第二阶段：港股。
3. 第三阶段：日本股票、韩国股票。

### 6.2 能力矩阵

| 证据块 | A 股 | 美股 | 港股 | 日本/韩国 |
|---|---|---|---|---|
| 行情与完整日线 | 必需 | 必需 | 必需 | 必需 |
| 财务报表 | 必需 | 必需 | 必需 | 必需但允许受限 |
| 估值 | 必需 | 必需 | 必需 | 必需但允许受限 |
| 公告/财报事件 | 必需 | 必需 | 必需 | 尽力提供 |
| 新闻 | 必需 | 必需 | 必需 | 尽力提供 |
| 行业/市场结构 | 必需 | 必需 | 建议 | 尽力提供 |
| 股东/内部人 | 建议 | 建议 | 建议 | 可选 |
| 资金流 | 建议 | `not_supported` 或市场专用实现 | 可选 | `not_supported` |
| 质押/解禁/减持 | A 股专用 | 使用美股对应披露，不复用 A 股语义 | 市场专用 | `not_supported` 或市场专用 |
| 筹码分布/龙虎榜/北向 | A 股专用 | `not_supported` | 仅使用港股对应数据 | `not_supported` |

### 6.3 数据源策略

1. Provider 按市场和数据类型注册，不允许全局硬编码一个优先级。
2. 免费数据源提供可运行基线；Token/付费源作为可选稳定增强。
3. 同一请求按 provider chain 依次尝试，记录每次尝试、成功源、回退源和耗时。
4. 允许 last-good cache，但必须标记陈旧时间；超过市场/字段上限后不得继续用于积极动作。
5. Provider 全部失败与真实无数据必须区分为 `fetch_failed` 和 `missing/not_supported`。
6. Phase 0 必须完成许可证、缓存、再分发、商用和署名检查，再确定生产 provider。

## 7. 运行架构

```text
创建/更新诊断
  -> 规范化标的 + 冻结决策画像
  -> 创建 DiagnosisRun + 积分预留
  -> Provider Registry 并发取数
  -> 标准化 + EvidencePack + 数据质量
  -> 确定性指标计算
  -> 六维度独立分析
  -> 冲突检测
       -> 无冲突：跳过复核
       -> 有冲突：定向 ConflictReview
  -> 质量门禁 + 确定性 RiskAssessment
  -> 七态动作校验
  -> 原子提交 DiagnosisVersion + 积分结算
  -> 生成后验评估计划与监控基线
```

目标架构继续复用现有 `deep_analysis` worker 的认领、租约、心跳、重试和积分逻辑；当前 remediation 只建立 `diagnosis_files`、`diagnosis_versions`、`diagnosis_runs` 持久化契约，尚未完成 worker 收敛或事务集成。不要继续把运行状态和不可变结果塞在一行中。

目标运行语义是 `at-least-once execution, at-most-once version commit`。同一租约只能提交一个版本；旧 worker 恢复后不能写入、结算或发送提醒。这些行为仍需父任务实现并验证。

## 8. 多轮问答

### 8.1 绑定规则

1. 一个诊断问答会话属于一个诊断档案。
2. 每轮问答显式记录所引用的 `diagnosis_version_id`。
3. 默认引用用户当前查看的版本，不自动跳到最新版本。
4. 问答只读取该版本的低敏摘要、证据索引和必要证据项，不把完整原始 provider payload 注入模型。
5. 回答中的关键事实引用 `evidence_id`；无法从版本证据回答时，明确提示“当前版本未包含此证据”。
6. 用户要求“用最新数据看看”“更新结论”时，界面先展示将创建新版本，再调用更新接口。

### 8.2 上下文压缩

长会话可压缩用户可见对话，但诊断版本、证据引用、已确认偏好和未决问题必须作为结构化状态保存，不能只依赖 LLM 摘要。

### 8.3 Chat 与档案入口

- 普通 Chat 识别到股票诊断意图时，可创建档案或选择已有档案。
- 档案页面内嵌问答区，天然绑定当前版本。
- Chat 中出现的新闻或社媒内容可以作为“用户提供材料”进入下一次显式更新，但不能直接改写当前版本。

## 9. 更新提醒与版本比较

### 9.1 更新提醒来源

- 新财报或业绩预告；
- 重大公告、监管、诉讼、管理层或资本动作；
- 价格触及诊断失效条件；
- 关键证据超过时效上限；
- 行业或市场阶段发生显著变化；
- 新证据与现有核心论点冲突。

提醒只保存触发事实、相关证据和潜在影响，不提前生成新建议。用户确认后才创建 `DiagnosisRun`。

### 9.2 版本 diff

比较必须区分四类变化：

1. `evidence_change`：财务、价格、事件等事实变化。
2. `profile_change`：持仓状态、周期或风险偏好变化。
3. `method_change`：规则、模型、权重或 provider 版本变化。
4. `advice_change`：动作、触发或失效条件变化。

界面不能只显示“Buy → Hold”，必须解释由哪一类变化导致。

## 10. 后验评估与校准

### 10.1 观察内容

- 目标周期收益；
- 最大有利波动和最大不利波动；
- 是否触发失效条件；
- 触发条件是否曾满足；
- 数据是否足以评估；
- 用户反馈 `useful/not_useful`，与价格结果分开统计。

### 10.2 统计维度

- 市场；
- 诊断动作；
- 主周期；
- 决策画像；
- 数据质量；
- 市场阶段；
- 分析维度；
- 分析版本。

以下最小样本量是待离线评估验证的初始门槛，不代表当前已实现能力：

| 市场 | 最小样本量 | 原因 |
|------|-----------|------|
| A 股 | 30 | 用户主要市场，积累快 |
| 美股 | 30 | 同 A 股 |
| 港股 | 20 | 第二批上线，标的范围小 |
| 日本 | 15 | 第三批，但散户活跃 |
| 韩国 | 12 | 第三批，标的和用户量最小 |

不足时只显示"已收集 N/M 个样本"，不展示任何统计数据。统计是诊断建议的后验表现，不是实盘或组合收益。

### 10.3 校准边界

后验服务只能生成权重和门槛调整建议。任何采用都必须人工审阅、通过固定评估集，并产生新的 `analysis_version`。禁止运行时在线改权。

## 11. API 设计

建议新增领域 API，同时保留 `/api/deep-analysis` 作为过渡适配层：

| 方法 | 路径 | 语义 |
|---|---|---|
| POST | `/api/diagnosis-files` | 为规范化标的创建或返回现有档案 |
| GET | `/api/diagnosis-files` | 查询用户诊断档案 |
| GET | `/api/diagnosis-files/{file_id}` | 档案摘要、当前版本和待处理提醒 |
| POST | `/api/diagnosis-files/{file_id}/runs` | 创建首次诊断或显式更新任务 |
| GET | `/api/diagnosis-runs/{run_id}` | 查询执行阶段、进度和错误 |
| POST | `/api/diagnosis-runs/{run_id}/cancel` | 取消运行任务 |
| GET | `/api/diagnosis-files/{file_id}/versions` | 版本列表 |
| GET | `/api/diagnosis-versions/{version_id}` | 读取结构化诊断版本 |
| GET | `/api/diagnosis-versions/{a}/diff/{b}` | 读取版本变化归因 |
| POST | `/api/diagnosis-files/{file_id}/conversations` | 创建绑定档案的问答会话 |
| POST | `/api/diagnosis-conversations/{id}/messages` | 对指定版本提问 |
| GET | `/api/diagnosis-files/{file_id}/reminders` | 查询更新提醒 |
| POST | `/api/diagnosis-reminders/{id}/confirm` | 确认提醒并创建更新任务 |
| POST | `/api/diagnosis-reminders/{id}/dismiss` | 忽略提醒，不创建更新任务 |
| DELETE | `/api/diagnosis-files/{file_id}` | 软删除档案及关联数据（需所有权验证） |
| GET | `/api/diagnosis-files/{file_id}/outcomes` | 查询后验结果 |

缓存命中必须比较 `instrument + decision_profile_snapshot + analysis_version + evidence freshness`。不同持仓状态或主周期不能误用同一份最终建议缓存；可以复用 EvidencePack，但需重新生成决策解释层。

## 12. 前端工作区

建议新增：

```text
/diagnosis
/diagnosis/:fileId
```

档案页布局：

1. 顶部：标的、市场、当前版本、诊断时点、主周期、诊断可用性。
2. 核心建议：七态动作、触发条件、失效条件、执行调整和风险原因。
3. 周期视图：短期、中期、长期分别展示，主周期突出但不隐藏其他周期。
4. 维度意见：六维度状态、方向、证据和缺失项。
5. 分歧与风险：反方意见、冲突是否解决、风险如何改变最终动作。
6. 证据抽屉：来源、时点、单位、报告期、回退和数据质量。
7. 版本时间线：版本 diff 和变化归因。
8. 更新提醒：查看变化、忽略或确认更新。
9. 后验结果：样本和观察结果，不展示虚假收益承诺。
10. 问答侧栏：固定显示当前引用版本，显式切换版本。

运行页显示真实阶段：取数、标准化、指标计算、维度分析、冲突复核、风险约束、提交版本。进度不得用固定 sleep 或伪线性百分比。

## 13. 分阶段实施计划

### Phase 0：能力真实性与数据门禁

目标：先确认系统真正能取到什么、能合法保存什么、能稳定执行什么。

工作项：

1. 建立股票 Skill 依赖闭包检查：Skill 声明的 references、scripts、tools 和依赖 Skill 必须随物化进入工作区。
2. 对当前所有股票 Skill 标记 `runnable/degraded/unavailable`，不可运行的 Skill 不进入诊断编排。
3. 确认 A 股、美股的免费与增强 provider 候选、许可证、字段、时效、缓存和再分发边界。
4. 建立 Instrument Registry 和固定脱敏 fixture；至少覆盖正常、缺失、单位异常、名称歧义和停牌标的。
5. 定义 EvidencePack、数据质量状态、主周期必需块和 live contract tests。
6. 盘点旧 `deep_analysis` 设计与当前代码差异，冻结迁移方案。

门禁：没有通过 provider 合约测试和 Skill 依赖闭包检查，不进入真实诊断实现。

### Phase 1：诊断档案与不可变版本基础

目标：建立正确的数据模型和可审计输入，不追求完整分析维度。

工作项：

1. 已建立 DiagnosisFile、DiagnosisVersion、DecisionProfile 和 EvidencePack 快照契约。
2. 已建立 DiagnosisRun 持久化形状；DeepAnalysis worker 收敛仍是父任务工作。
3. 已实现 A 股规范化和美股 ticker 识别；真实 provider 接入仍是父任务工作。
4. 已实现 provider attempt/fallback 构建机制和数据质量门禁；last-good cache 与 source health 尚未实现。
5. 已实现版本身份和数据库完整性约束；真实不可变提交事务、所有权 API、删除和缓存工作流尚未实现。
6. 已提供确定性 `limited/insufficient` scaffold；mock diagnosis router 保持未挂载。

门禁：同一快照可重放、每项证据可追溯、问答或任务重试不能改写已提交版本。

### Phase 2：真实诊断 Runner

目标：替换 Mock，形成 A 股和美股首个可执行闭环。

工作项：

1. 实现确定性财务、估值、技术和风险指标。
2. 实现六个维度意见及严格 Schema 校验。
3. 实现方向冲突检测与条件式 ConflictReview。
4. 实现质量门禁、确定性风险约束和七态动作校验。
5. 实现短中长期结论及主周期最终建议。
6. 记录模型、prompt、provider、token、耗时和规则版本。
7. 建立单 Agent、纯确定性和新 Runner 三组固定评估基线。

门禁：不存在无证据积极动作；所有动作转换可解释；重复运行的动作稳定性达到评估门槛。

### Phase 3：档案工作区与多轮问答

目标：让诊断成为产品主对象，而不是后台 JSON。

工作项：

1. 新增档案列表和详情页面。
2. 实现版本选择、证据抽屉、分周期视图、分歧与风险解释。
3. 建立 Thread 与 DiagnosisFile/Version 的显式绑定。
4. 实现版本固定问答、证据引用和显式更新确认。
5. 普通 Chat 可创建或跳转诊断档案。
6. 兼容旧 `/api/deep-analysis` 调用和历史记录。

门禁：普通问答不会新建或改写版本；刷新页面后仍能恢复引用版本与问答历史。

### Phase 4：更新提醒、版本 diff 与后验闭环

目标：从“能诊断”升级为“持续诊断”。

工作项：

1. 实现新财报、重大事件、失效条件和数据过期监控。
2. 实现 UpdateReminder 与用户确认更新。
3. 实现 evidence/profile/method/advice 四类版本 diff。
4. 实现 5/20/60/120 交易日后验观察任务。
5. 实现按市场、动作、周期、画像和质量分组统计。
6. 实现用户有用性反馈，并与价格结果分离。

门禁：提醒不会静默生成版本；样本不足不展示胜率；评估失败不影响诊断主链。

### Phase 5：市场扩展

顺序：港股，然后日本股票与韩国股票。

每增加一个市场必须独立完成：

1. Instrument 规范化与交易日历；
2. provider 合约与许可证；
3. EvidencePack 能力矩阵；
4. 市场专用 Prompt 和风险规则；
5. `not_supported` 语义；
6. 固定 fixture 与 live contract tests；
7. 数据质量阈值和 Beta 门禁。

禁止仅放开 API 枚举就宣称支持新市场。

### Phase 6：候选、组合与校准增强

1. 选股结果一键创建诊断档案，但选股与诊断保持独立契约。
2. 自选股和最小持仓上下文进入更新提醒与决策画像。
3. 后验样本充足后生成维度权重调整建议。
4. Provider Doctor 和市场能力状态页。
5. 只在前述闭环稳定后考虑更细周期或更多维度。

## 14. 测试与验收

### 14.1 契约验收

- 100% 最终事实与意见引用可解析的 `evidence_id`。
- 100% 证据项具有状态；可用数值具有来源和时点。
- 币种、单位、报告期和市场语义经过标准化。
- 未完成日线永远不会标为完整日线。
- 市场特有字段不会跨市场伪映射。

### 14.2 动作验收

- `buy/add` 必须是 `actionable`，且具备周期、触发和失效条件。
- `limited/insufficient` 不得产生积极动作。
- 风险约束只能降低动作积极程度。
- 空仓与持仓动作集合严格隔离。
- 模型输出非法价格关系时必须降级或阻断。

### 14.3 版本与问答验收

- 已提交 DiagnosisVersion 不可更新。
- 同一运行重试最多提交一个版本并结算一次积分。
- 每轮诊断问答能恢复其引用版本。
- 普通问答不触发 provider 请求或新版本。
- 版本 diff 能区分证据、画像、方法和建议变化。

### 14.4 运行验收

- 两个 worker 不会重复提交同一版本。
- API/worker 重启后可恢复任务。
- provider fallback、stale cache 和全失败均有不同状态。
- 单维度失败不会伪装成 neutral，也不会必然拖垮全部任务。
- 任务阶段、provider 尝试、模型调用和积分状态可观测。

### 14.5 质量评估

固定评估集必须使用当时可见数据，避免未来信息泄漏。至少比较：

1. 当前 D-sight 单 Agent 基线；
2. 纯确定性指标基线；
3. 新诊断 Runner。

指标包括证据一致性、动作稳定性、方向表现、最大不利波动、校准误差、人工评分、数据覆盖、成本和延迟。未明显优于基线前保持 Beta，不宣称提高收益。

建议的初始运行目标为：创建任务接口 P95 小于 2 秒；A/US 完整诊断 P95 不超过现有 300 秒任务预算。数值需在 Phase 2 基准测试后重新确认，不能直接作为未经验证的 SLA。

## 15. 风险与控制

| 风险 | 根因 | 控制 |
|---|---|---|
| Skill 宣称可用但运行失败 | 资源和依赖未随 Skill 物化 | Phase 0 依赖闭包门禁 |
| 数据源突然失效 | 免费接口变更、限流或区域限制 | provider chain、last-good、health、live contract test |
| 跨市场概念污染 | 用统一模板替代市场能力矩阵 | 市场专用 capability 与 `not_supported` |
| LLM 编造证据 | 允许自由取数或自由计算 | 共享 EvidencePack、证据引用校验、确定性计算 |
| 多 Agent 伪共识 | 相关方法重复计票 | 维度聚类、冲突复核、禁止人数投票 |
| 版本不可复现 | 缓存身份只含可读版本号 | 完整 analysis fingerprint |
| 问答隐式改变结论 | 会话和诊断状态混在一起 | 版本固定问答、显式更新 |
| 后验过拟合 | 小样本在线调权 | 最小样本、离线评估、人工启用新版本 |
| 用户误解为投资顾问 | 只展示动作和置信度 | 条件化建议、风险证据、数据质量、免责声明 |
| 任务与版本耦合 | 用一行记录运行和最终结果 | DiagnosisRun 与 DiagnosisVersion 分离 |

## 16. 建议的代码边界

以下是实施时的建议边界，不代表本次已创建文件：

```text
backend/app/diagnosis/
├── models.py              # File/Version/Profile/Reminder/Outcome
├── schemas.py             # 公开 API 契约
├── instrument.py          # 市场与标的规范化
├── evidence/
│   ├── schemas.py
│   ├── builder.py
│   ├── quality.py
│   └── providers/
├── dimensions/
│   ├── base.py
│   ├── registry.py
│   └── ...
├── conflict.py
├── risk.py
├── advice.py
├── runner.py
├── service.py
├── reminders.py
├── outcomes.py
└── router.py

frontend/src/diagnosis/
├── api.ts
├── types.ts
├── DiagnosisListPage.tsx
├── DiagnosisWorkspace.tsx
├── VersionTimeline.tsx
├── EvidenceDrawer.tsx
├── HorizonView.tsx
├── ConflictAndRisk.tsx
├── ReminderPanel.tsx
├── OutcomePanel.tsx
└── DiagnosisChat.tsx
```

现有 `backend/app/deep_analysis/worker.py` 的可靠执行逻辑应提取或复用，不要在 `diagnosis/` 再复制一套 worker。旧 API 作为适配层逐步迁移，等真实调用方全部切换后再决定是否移除。

## 17. 推荐下一步

下一步不是开始写 Runner，而是执行 Phase 0：先修复 Skill 依赖闭包、完成 A 股/美股 provider 与许可证矩阵、冻结 EvidencePack 契约和固定评估 fixture。只有这四项通过，真实诊断实现才有稳定地基。
