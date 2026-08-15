# 股票诊断设计文档审阅报告

审阅日期：2026-08-11。
审阅范围：主设计文档(`stock-diagnosis-design-plan.md`) + 3个 ADR + Phase 0 任务文档 + 已有代码。

---

## 1. 主设计文档

### 1.1 缺失 DecisionProfileSnapshot 契约 [重要]

**位置**: 第 4 节领域模型 + 第 5 节核心契约

`DiagnosisVersion` 引用了 `DecisionProfileSnapshot`（决策画像快照），它直接影响最终建议——持仓状态决定动作空间、主周期决定证据权重、风险偏好影响动作积极程度。但整个第 5 节没有任何地方定义它。

**风险**: 进入 Phase 1（数据库建模）时缺少这个对象的字段约定；进入 Phase 2（Runner）时缺少对"持仓-动作校验"的形式化依据。

**修复建议**: 在第 5 节（核心契约）增设 5.0，内容如下：

```python
class PositionType(Enum):
    NONE = "none"        # 空仓：允许 buy / watch / avoid
    HOLDING = "holding"  # 持仓：允许 add / hold / reduce / sell

class DecisionProfileSnapshot:
    """
    创建诊断版本时冻结的决策画像快照。
    同一档案中不同版本可以有不同的画像，
    但同一版本中的所有维度共享同一画像。
    """
    position: PositionType
    primary_horizon: Literal["short", "medium", "long"]

    # 风险偏好：conservative 会拉高入场门槛
    risk_tolerance: Literal["conservative", "moderate", "aggressive"]

    # 持仓上下文（position=HOLDING 时必需）
    portfolio_weight: float | None   # 占组合比例，0.0-1.0
    cost_basis: float | None         # 持仓均价（成本基准）
    entry_date: date | None          # 建仓日期

    # 用户约束
    max_position_weight: float       # 单只股票最大持仓占比
    tags: list[str]                  # 用户自定义标签（如 "核心仓位""观察仓"）

    # 画像变更原因（手动/系统规则触发）
    changed_from: str | None         # 上一个快照的 profile_id
    change_reason: str | None
```

**约束**:
- 空仓画像 (`none`) 只允许动作 `buy / watch / avoid`
- 持仓画像 (`holding`) 只允许 `add / hold / reduce / sell`
- `risk_tolerance=conservative` 时，即使维度方向偏多，买入触发条件也必须更严格（如要求 >50% 的安全边际）
- `portfolio_weight + 拟增仓位 > max_position_weight` 时，`add` 自动降级为 `hold`

---

### 1.2 DimensionOpinion.direction 的 `unknown` 与 `neutral` 语义重叠 [中等]

**位置**: 第 5.4 节

```python
direction: Literal["bullish", "neutral", "bearish", "unknown"]
```

当前存在四种值，但问题在于：

- `unknown`：数据不足、无法判断方向 → 但这个语义已经被 `status = "unavailable" | "failed"` 覆盖
- `neutral`：数据充分、判断为中性 → 这是一个有效的分析结论

当 `status != success` 时 `direction` 是什么值？如果也是 `unknown`，那 `direction=unknown` 可能来自两种完全不同的情况：数据不足的静默失败 vs 数据充足但无法判断方向。前者应该阻止进入决策，后者应该正常进入。

**修复建议**:

```python
direction: Literal["bullish", "neutral", "bearish"]
```

规则：
- `status == "success"` 时，`direction` 必须为 `bullish / neutral / bearish` 之一
- `status == "degraded"` 时，`direction` 可正常赋值但必须附 `warnings` 说明降级原因
- `status == "unavailable" | "failed"` 时，`direction` 实际不参与决策，其值约定为 `neutral`（不作为中性投票，仅作为空占位）
- 冲突检测时只考虑 `status == success` 的维度；`degraded` 维度参与但权重降低

另：`confidence` 目前是 `float | None`，但无范围约束。建议明确 `[0.0, 1.0]` 或 `[0, 100]`，并在 5.4 节增加注释"confidence 表示该维度内部证据的一致性和完整性，不表示方向预测准确率"。

---

### 1.3 持仓比例风险约束缺失 [中等]

**位置**: 第 5.6 节风险规则列表

当前风险规则覆盖了流动性、波动、财务、事件、数据陈旧、价格关系、追高、市场阶段共 8 项。缺少一项关键规则：**持仓集中度约束**。

**场景**: 用户已持有某股票占总组合 30%，画像中的 `max_position_weight` 为 20%。此时即使诊断建议 `add`，也应被风险层降级为 `hold`。

**风险**: 如果没有这条规则，诊断系统可能在用户已超配时鼓励加仓，增加实质性集中度风险。

**修复建议**: 在 5.6 节风险规则列表中增加第 9 项：

> 9. **持仓集中度超标**: 若画像 `position = holding` 且 `portfolio_weight + 拟增权重 > max_position_weight`，则 `add` 降级为 `hold`。此规则不依赖市场数据，属于确定性约束，不允许模型绕过。

另：考虑到 `portfolio_context` 证据块中可能也有仓位信息，需要明确优先取 `DecisionProfileSnapshot` 中的值（用户显式设置），仅在画像未设置时使用证据块中的值（系统推断）。

---

### 1.4 analysis_version 指纹中"实际模型 ID"可能导致缓存过度失效 [中等]

**位置**: 第 5.8 节

> analysis_version 必须由以下内容生成稳定指纹：... prompt 版本和实际模型 ID

将"实际模型 ID"（如 `claude-sonnet-4-5-20251001`）纳入指纹的后果：每次 Anthropic 发一个 patch 版本号变化，所有已缓存的 EvidencePack 和维度缓存全部失效。但同一模型族内的 patch 版本输出在结构化 Schema 约束下差异极小。

**修复建议**: 将"实际模型 ID"拆分为指纹因子和可观测元数据：

纳入指纹：
- `model_family`：如 `claude`、`gpt`
- `model_tier`：如 `sonnet`、`fable`、`pro`
- `model_variant`：如 `4.5`（不含 patch 号）

不纳入指纹、仅记录在 Provenance 中：
- 实际 model_id（含 patch 号）
- 实际 API endpoint
- temperature、max_tokens 等运行时参数

指纹构造逻辑变为：

```python
def compute_analysis_fingerprint(
    evidence_schema_version: str,
    provider_rules_version: str,
    indicator_version: str,
    dimension_registry_version: str,
    prompt_version: str,
    model_family: str,
    model_tier: str,
    model_variant: str,
    conflict_rules_version: str,
    quality_threshold_version: str,
    risk_rules_version: str,
    action_mapping_version: str,
) -> str:
    """生成稳定的分析版本指纹。"""
    ...
```

---

### 1.5 `not_supported` 状态应排除在质量分计算之外 [中等]

**位置**: 第 5.2 节 + 第 6.2 节

能力矩阵中明确美股 `capital_flow` 为 `not_supported`、日韩 `ownership` 为可选/`not_supported`。但 5.2 节未说明 `not_supported` 如何处理在 `quality_score` 和 `completeness` 中。

**场景**: 美股诊断中 `capital_flow` 永远为 `not_supported`。如果按现有 EvidencePack schemas.py 的逻辑（所有项等权加总），`not_supported` 会作为 `status=not_supported` 计入分母，但质量系数为 0，拉低美股诊断的总分。这不合理——一个市场不支持的数据不应该是"低质量"。

**修复建议**: 在 5.2 节增加规则：

> 状态为 `not_supported` 的块和证据项不计入 `quality_score` 分母和 `completeness` 分母。它们只出现在证据包的元数据中作为"当前市场未覆盖"的标记。但这不改变主周期必需块的判定——若必需块为 `not_supported`，则该市场该周期不可用。

已在 schemas.py 中实现时，`_update_metrics()` 需区分 `not_supported` 与其他状态：

```python
def _update_metrics(self):
    """Update quality score and completeness, excluding not_supported."""
    if not self.blocks:
        self.quality_score = 0.0
        self.completeness = 0.0
        return

    total_items = 0  # 不包括 not_supported
    ...  # 跳过 status == EvidenceStatus.not_supported 的项
```

---

### 1.6 后验评估最小样本量应分市场设定 [低]

**位置**: 第 10.2 节

> 每个 bucket 建议至少 30 个已完成样本才显示命中率或均值

该阈值对 A 股和美股合理，但港股和日韩市场积累 30 个样本需要更长时间。固定阈值会导致后发市场长时间处于"样本不足"状态。

**修复建议**:

| 市场 | 最小样本量 | 原因 |
|------|-----------|------|
| A 股 | 30 | 用户主要市场，样本积累快 |
| 美股 | 30 | 同 A 股 |
| 港股 | 20 | 第二批上线，单市场标的少 |
| 日本 | 15 | 第三批上线，但日本散户活跃 |
| 韩国 | 12 | 第三批上线，标的范围和用户量最小 |

未达阈值时展示格式为"已收集 7/20 个样本"，而不显示任何统计数据。

---

### 1.7 API 设计缺失两个端点 [低]

**位置**: 第 11 节

缺失的端点：

**1. 忽略提醒**

```text
POST /api/diagnosis-reminders/{id}/dismiss
```

语义：用户认为当前提醒无价值，标记为已忽略。与确认更新的区别是不创建 DiagnosisRun。提醒被 dismiss 后不再在档案页显示，但提醒本身保留为历史记录。

**2. 删除档案**

```text
DELETE /api/diagnosis-files/{file_id}
```

语义：软删除档案及所有关联的版本、问答、提醒、后验记录。关联的 Thread 只解除诊断绑定（不解散 Thread）。需确认用户所有权后方可执行。

---

## 2. ADR 文档

三个 ADR 的核心结论和推到方向是正确的，但有两个不足：

### 2.1 缺少 ADR 标准字段 [低]

每个 ADR 只有一段总结性描述，缺少标准 ADR 所需的结构化字段。建议每个 ADR 补全：

```markdown
# ADR-000X: [标题]

- **状态**: 已采纳
- **日期**: 2026-08-10
- **决策者**: lwx

## 背景
[为什么需要做这个决策？当前问题是什么？]

## 决策
[我们决定怎么做？]

## 考虑的替代方案

### 方案 A: [描述]
- 优点: ...
- 缺点: ...

### 方案 B: [描述]
- 优点: ...
- 缺点: ...

## 后果

### 正面
- ...

### 负面
- ...

### 中性
- ...
```

以 ADR-0003 为例，缺失的关键信息：
- **替代方案 A**: 可变版本 + 完整审计日志——优点是有更少的存储对象、缺点是 diff 计算复杂、并发写冲突
- **替代方案 B**: 仅在动作变化时创建版本——节省存储，但无法回答"为什么上次是 Hold"之外的细节
- **选择 (不可变版本) 的代价**: 每只股票每月可能产生 1-4 个版本，每版本约 50-200KB，需要版本保留策略

### 2.2 ADR-0004 缺少触发阈值定义 [中等]

ADR-0004 说"仅在实质冲突时复核"但没有说什么是"实质冲突"。主设计文档 5.5 节列了 5 个触发条件，但 ADR 应该引用这些条件并注明这是平衡性的选择——之前考虑过"全部复核"或"永不复核"两种极端，选了折中方案。

另外缺少一个重要的设计权衡：**当 6 个维度中 3 个 Bullish、3 个 Bearish 时，算冲突还是不相关？** 答案是：只在同一周期内冲突才算（短期的 bullish 和长期的 bearish 是正常的多周期矛盾）。

---

## 3. Phase 0 任务文档

### 3.1 design.md 引用不存在的 data_providers 目录 [低]

> Audit existing providers in `backend/app/data_providers/`

`backend/app/data_providers/` 不存在。实际的数据获取逻辑分散在：
- `backend/app/agent/tools/stock.py`（AkShare 调用）
- 潜在的各 Skill 独立 provider 实现

`provider_matrix.md` 已正确记录了这一点，但 design.md 仍是错的。修复：改为引用实际的 provider 位置。

### 3.2 Instrument 模型有两份不一致的定义 [低]

| 字段 | 主设计文档 (5.1) | Phase 0 design.md + schemas.py |
|------|-----------------|-------------------------------|
| `original_input` | 无 | 有 |
| `normalization_method` | 无 | 有 |
| `ambiguity_resolved` | 无 | 有 |
| `candidates` | 无 | 有 |

实际代码（schemas.py）版本的 Instrument 更完整、更适合 Phase 0 需求（需要记录规范化过程）。主设计文档应同步更新到代码版本，而不是保留精简版。

### 3.3 implement.md Timeline 不符合实际情况 [低]

估计 10-16 天对于一个"验证阶段"偏高，且已经有 `audit/`、`evidence/schemas.py`、`instrument.py` 的基础代码（约 3 天的工作量已产出）。实际剩余工作量约 5-8 天。建议更新为诚实反映进度的数字。

---

## 4. 已有代码审查

### 4.1 EvidencePack._update_metrics 中 quality_score 权重过于简化 [中等]

```python
available=1.0, partial=0.5, fallback=0.3, stale=0.1, missing/fetch_failed/not_supported=0.0
```

所有证据块/项等权。但财务报表缺失对长期诊断的影响远大于新闻缺失。核心数据块（quote、fundamentals）应该有更高权重。

**修复建议**:

增加块级 (`evidence_block_weights`) 和状态级 (`evidence_status_weights`) 两级权重：

```python
# 证据块权重 — 按市场分，必需块权重 > 可选块
EVIDENCE_BLOCK_WEIGHTS = {
    'quote': 1.0,         # 任何诊断都依赖行情
    'fundamentals': 1.0,  # 中/长期核心
    'valuation': 0.9,
    'daily_bars': 0.8,
    'technical': 0.7,
    'events': 0.7,
    'market_context': 0.6,
    'news': 0.4,           # 补充性证据
    'ownership': 0.5,
    'capital_flow': 0.4,
    'portfolio_context': 0.5,
}

# 证据状态质量系数
EVIDENCE_STATUS_WEIGHTS = {
    EvidenceStatus.available: 1.0,
    EvidenceStatus.partial: 0.5,
    EvidenceStatus.fallback: 0.3,
    EvidenceStatus.stale: 0.1,
    EvidenceStatus.estimated: 0.4,
    EvidenceStatus.missing: 0.0,
    EvidenceStatus.not_supported: None,  # 不计入分母
    EvidenceStatus.fetch_failed: 0.0,
}

def _update_metrics(self):
    total_weight = 0.0
    weighted_score = 0.0

    for block in self.blocks.values():
        block_weight = EVIDENCE_BLOCK_WEIGHTS.get(block.block_id, 0.5)
        for item in block.items.values():
            status_weight = EVIDENCE_STATUS_WEIGHTS.get(item.status)
            if status_weight is None:  # not_supported
                continue
            weighted_score += block_weight * status_weight
            total_weight += block_weight

    self.quality_score = weighted_score / total_weight if total_weight > 0 else 0.0
    self.completeness = ...  # 类似逻辑，按 available 项占总权重比
```

这样：
- 美股 diagnosis（capital_flow 为 not_supported）不会因此扣分
- 缺少 fundamentals 的长期诊断得分大幅降低
- 缺少 news 的影响较小

### 4.2 EvidenceBlock._update_status 状态优先级逻辑 [低]

当前优先级 (从上到下)：
1. all available → `available`
2. any available → `partial`
3. any fallback → `fallback`
4. any stale → `stale`
5. else → `missing`

边界情况：
- 块内全部是 `stale` 且无 available/fallback → `stale` ✓
- 块内全部是 `fetch_failed` 且无其他 → `missing`（因为没有 stale/fallback/available 分支）—— 逻辑上正确但不够精确。建议增加 `fetch_failed` 分支，让块状态更精确反映原因。

**修复建议**:

```python
def _update_status(self):
    if not self.items:
        self.status = EvidenceStatus.missing
        self.completeness = 0.0
        return

    statuses = [item.status for item in self.items.values()]
    available_count = sum(1 for s in statuses if s == EvidenceStatus.available)
    self.completeness = available_count / len(statuses)

    if all(s == EvidenceStatus.available for s in statuses):
        self.status = EvidenceStatus.available
    elif any(s == EvidenceStatus.available for s in statuses):
        self.status = EvidenceStatus.partial
    elif any(s == EvidenceStatus.fetch_failed for s in statuses):
        self.status = EvidenceStatus.fetch_failed
    elif any(s == EvidenceStatus.fallback for s in statuses):
        self.status = EvidenceStatus.fallback
    elif any(s == EvidenceStatus.stale for s in statuses):
        self.status = EvidenceStatus.stale
    else:
        self.status = EvidenceStatus.missing
```

### 4.3 skill_audit.py 路径硬编码 [低]

```python
skills_dir = Path('backend/skills_data/skills')
```

相对路径依赖于 CWD。如果从项目根目录以外运行，技能审计失败。

**修复**: 基于 `__file__` 推导绝对路径

```python
import os
skills_dir = Path(__file__).resolve().parent.parent.parent / 'skills_data' / 'skills'
```

或者改为接受命令行参数 `--skills-dir`，方便在 CI 中指定不同路径。

### 4.4 skill_audit.py 的 Skill 发现依赖关键词匹配 [低]

```python
stock_keywords = ['stock', 'diagnosis', 'analysis', 'financial', 'investment', 'portfolio']
```

问题：`analysis` 会匹配到非股票的 skill（如情感分析）；`portfolio-review` 中的 `portfolio` 也会被匹配到，因为它包含 `portfolio`。

但这些关键词匹配到的不相关 Skill 因为关键词覆盖面太宽，会产生假阳性扫描，浪费审计时间。建议改为精确匹配：使用 skill 的 frontmatter 中的 `category` 或 `tags` 字段，或维护一个明确的白名单。

---

## 5. 修复优先级总览

| 序号 | 问题 | 位置 | 严重程度 | 建议修复时机 |
|------|------|------|----------|-------------|
| 1 | DecisionProfileSnapshot 契约缺失 | 主文档 5.0 | **重要** | Phase 1 开始前 |
| 2 | quality_score 块级权重 | schemas.py | **中等** | Phase 0 内 |
| 3 | `not_supported` 不计入质量分 | 主文档 5.2 + schemas.py | **中等** | Phase 0 内 |
| 4 | 持仓比例风险约束 | 主文档 5.6 | **中等** | Phase 2 开始前 |
| 5 | model ID 指纹过度细化 | 主文档 5.8 | **中等** | Phase 1 内 |
| 6 | `unknown`/`neutral` 语义 | 主文档 5.4 | **中等** | Phase 2 开始前 |
| 7 | ADR 缺少标准字段 | 3 个 ADR | 低 | Phase 0 内 |
| 8 | ADR-0004 缺少阈值定义 | ADR-0004 | 中等 | Phase 0 内 |
| 9 | design.md 引用错误路径 | Phase 0 design.md | 低 | Phase 0 内 |
| 10 | Instrument 模型不一致 | 主文档 5.1 | 低 | Phase 0 内 |
| 11 | evidence 块状态缺少 fetch_failed | schemas.py | 低 | Phase 0 内 |
| 12 | 后验样本量分市场 | 主文档 10.2 | 低 | Phase 4 前 |
| 13 | API 缺少 dismiss/delete | 主文档 11 | 低 | Phase 3 前 |
| 14 | skill_audit.py 路径硬编码 | skill_audit.py | 低 | Phase 0 内 |
| 15 | implement.md Timeline | Phase 0 implement.md | 低 | Phase 0 内 |

## 6. 未发现问题的部分

以下设计决策经审阅后确认合理，不需要修改：

- **领域模型**(第 4 节)：DiagnosisFile → Version → Run 的层级关系和不可变不变量设计正确
- **EvidencePack 作为共享输入**：所有维度共享同一份证据，是防止 LLM 幻觉的关键约束
- **冲突只在实质冲突时复核**：不做全量辩论，成本可控
- **风险只能降级不能升级**：不对称约束正确
- **后验离线评估、人工启用新版本**：不在线改权，安全
- **市场能力矩阵**：A 股特有概念不跨市场映射的设计原则正确
- **运行架构**：at-least-once run, at-most-once version commit 的语义完整
- **6 维度聚类**：首期不搞 13 个角色，减少伪共识
- **LLM 不做计算**：财务/技术/风险数值由确定性代码产出
- **provider chain + last-good cache + source health**: 数据源故障时的三层防护合理
- **4 类版本 diff**: evidence/profile/method/advice 的分解足够实用
- **API 缓存 key 设计**: instrument + profile + analysis_version + freshness 的组合正确
- **Phase 分拆和门禁设计**：Phase 0 不做实现、每阶段有明确门禁，执行纪律性强

---

## 7. 建议的执行顺序

**本次 Phase 0 内修复**（不影响其他阶段）：
1. schemas.py：quality_score 块级权重 + not_supported 排除 + fetch_failed 分支
2. 主文档 5.2：增加 `not_supported` 质量分规则
3. skill_audit.py：路径改为绝对路径
4. design.md：修正 data_providers 引用
5. Instrument 模型：同步主文档到代码版本
6. ADR：补充标准字段和 ADR-0004 阈值引用

**Phase 1 开始前**：
7. 补充 DecisionProfileSnapshot 契约
8. 确定 analysis_version 指纹因子定义

**Phase 2 开始前**：
9. DimensionOpinion direction 简化为 3 值
10. 持仓比例风险约束
