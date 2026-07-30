# Skill Router 动态编排设计

**日期**: 2026-07-30  
**状态**: 待实现

## 背景

当前 `build.py` 在每次 chat 请求时将用户所有已安装的 active skills 全量物化到 workspace，随着 skill 数量增长（目标 100+），会导致 token 浪费和响应变慢。

## 目标

- 每次请求只加载与用户意图相关的 capabilities（skill / tool / agent）
- 支持单 capability、顺序组合、并行组合三种执行模式，由显式 DAG orchestrator 强制执行
- LLM provider 可配置，不硬绑 DeepSeek
- 保持向后兼容：无匹配时降级为全量加载

## 架构

```
用户输入
  ↓
[门控] 轻量规则判断
  - 高置信无工具意图（寒暄、稳定概念问答）→ 直接回答，跳过 Stage 1/2
  - 其余 → 进入 Stage 1
  ↓
[Stage 1] Embedding 召回（pgvector）
  - 每个 capability 的 description + tags 向量化存 DB（Vector(EMBEDDING_DIM=1024)）
  - 召回 top-8 候选，~50ms，无 LLM 调用
  ↓
[Stage 2] LLM Planner（BaseChatModel，可配置 provider）
  - 输入：用户消息 + top-8 capability 的 {id, type, description, tags}
  - 输出：结构化执行计划（JSON）
  - ~500ms
  ↓
[DAG Orchestrator] 按计划强制执行
  - 按 step 顺序调度，parallel steps 并发执行
  - depends_on 依赖满足后才启动后续 step
  - 每个 step 物化对应 capabilities → DeepAgent 执行
  ↓
汇聚结果 → 返回
```

### Stage 2 输出格式

```json
{
  "plan": [
    {"step": 1, "capabilities": ["investment-research"], "mode": "single"},
    {"step": 2, "capabilities": ["earnings-review", "news-pulse"], "mode": "parallel"},
    {"step": 3, "capabilities": ["investment-checklist"], "mode": "single", "depends_on": [1, 2]}
  ],
  "direct_answer": false,
  "fallback": false
}
```

`mode` 枚举：`single` | `sequential` | `parallel`

### Capability Registry

Router 统一管理三类 capability，首期只注册 skill 和现有 tools：

| type | 首期来源 | 未来扩展 |
|------|----------|----------|
| `skill` | `skills` 表（SKILL.md） | 更多领域 skill |
| `tool` | `build.py` 中的内置工具 | 外部 API 工具 |
| `agent` | — | specialist agents |

### Fallback 策略

- Stage 1 所有候选相似度低于阈值（默认 0.5）→ `fallback: true`，跳过 Stage 2，全量加载（保持现有行为）
- Stage 2 LLM 超时或报错 → 同上降级

### ⚠️ Checkpoint 缓存问题

`deepagents/middleware/skills.py:960` 在 `skills_metadata` 已存在于 state 时直接跳过加载：

```python
if "skills_metadata" in state:
    return None
```

**影响**：同一 thread 第二轮起，Router 动态选择的 capabilities 无法生效，DeepAgent 复用首轮 checkpoint 中的元数据。

**处理策略**：在每轮 `build_agent` 调用前，从 LangGraph state 中清除 `skills_metadata` key，强制每轮重新加载。实现时需验证 checkpointer 的 state patch 接口。

## 涉及文件

| 文件 | 改动 |
|------|------|
| `backend/app/skills/models.py` | 加 `embedding Vector(EMBEDDING_DIM)` 字段（nullable，存量回填后收紧）；`category` 字段已存在，无需新增 |
| `backend/app/skills/seed.py` | 改用 YAML 解析 frontmatter（复用已有 PyYAML）；同步 `quantSkills.category` 和 `tags` 到 DB；内容指纹驱动增量 embedding 回填（复用 `get_embedding_provider()`，不全量调用） |
| `backend/alembic/versions/` | **新增 migration**：`skills` 表加 `embedding vector(1024)` 列 + HNSW 索引（参考 `e01f2c79ec7c_kb.py`）；在 `alembic/env.py:include_object` 中豁免新 HNSW 索引 |
| `backend/app/agent/capability_registry.py` | **新增**：Capability 元数据模型（id, type, description, tags）；首期注册 skill + 内置 tools |
| `backend/app/agent/router.py` | **新增**：CapabilityRouter 类，封装门控 + Stage 1 + Stage 2 |
| `backend/app/agent/orchestrator.py` | **新增**：DAG Orchestrator，按 RoutePlan 强制执行 step/parallel/depends_on |
| `backend/app/agent/build.py` | 接入 CapabilityRouter + Orchestrator；每轮清除 state 中的 `skills_metadata` |
| `backend/app/chat/router.py` | 构造 CapabilityRouter 实例（注入可配置 LLM）传给 build_agent |

## CapabilityRouter 接口

```python
class CapabilityRouter:
    def __init__(self, llm: BaseChatModel, db: AsyncSession, top_k: int = 8, threshold: float = 0.5):
        ...

    async def route(self, user_message: str, user_capabilities: list[Capability]) -> RoutePlan:
        # 门控：高置信无工具意图 → direct_answer=True
        # Stage 1: embedding 召回
        # Stage 2: LLM 规划
        # 返回 RoutePlan（含 plan steps、direct_answer 或 fallback=True）
        ...
```

## LLM Provider 配置

- Router 接收 `BaseChatModel` 实例，不硬绑 DeepSeek
- 配置项：`ROUTER_LLM_PROVIDER`（env），默认复用 `ChatDeepSeek`
- 未来可替换为任意 LangChain-compatible model

## Embedding 规范

- 维度：`EMBEDDING_DIM = 1024`，引用 `app/kb/models.py` 中的共享常量
- 向量化内容：`description + " " + " ".join(tags)`（tags 来自 frontmatter `quantSkills.tags`）
- 增量策略：存储 `embedding_source_hash`，内容或模型版本变化时才重算
- Seed 失败策略：embedding 失败不阻断 skill 导入，记录警告，该 skill 在 Stage 1 中降级为全文匹配

## 分层扩展（预留，100+ capabilities 时启用）

- `skills.category` 字段已存在（`models.py:20`），seed 需修复解析逻辑使其真正生效
- Stage 1 超过 100 个 capability 时，先按 category 过滤再做向量检索
- 无需改动 CapabilityRouter 接口，只改 Stage 1 内部实现

## 不在本次范围内

- 前端展示 Router 决策过程
- Router 决策结果缓存
- 用户手动覆盖 Router 选择
- specialist agent 类型的 capability（首期只有 skill + tool）
