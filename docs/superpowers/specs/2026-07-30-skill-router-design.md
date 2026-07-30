# Skill Router 动态编排设计

**日期**: 2026-07-30  
**状态**: 待实现

## 背景

当前 `build.py` 在每次 chat 请求时将用户所有已安装的 active skills 全量物化到 workspace，随着 skill 数量增长（目标 100+），会导致 token 浪费和响应变慢。

## 目标

- 每次请求只加载与用户意图相关的 skills
- 支持单 skill、顺序组合、并行组合三种执行模式
- LLM provider 可配置，不硬绑 DeepSeek
- 保持向后兼容：无匹配时降级为全量加载

## 架构

```
用户输入
  ↓
[Stage 1] Embedding 召回（pgvector）
  - 每个 skill 的 description + triggers 向量化存 DB
  - 召回 top-8 候选，~50ms，无 LLM 调用
  ↓
[Stage 2] LLM Router（BaseChatModel，可配置 provider）
  - 输入：用户消息 + top-8 skill 的 {slug, description, triggers}
  - 输出：结构化执行计划（JSON）
  - ~500ms
  ↓
物化选中 skills → DeepAgent 执行
```

### Stage 2 输出格式

```json
{
  "plan": [
    {"step": 1, "skills": ["investment-research"], "mode": "single"},
    {"step": 2, "skills": ["earnings-review", "news-pulse"], "mode": "parallel"},
    {"step": 3, "skills": ["investment-checklist"], "mode": "single", "depends_on": [1, 2]}
  ],
  "fallback": false
}
```

`mode` 枚举：`single` | `sequential` | `parallel`

### Fallback 策略

- Stage 1 所有候选相似度低于阈值（默认 0.5）→ `fallback: true`，跳过 Stage 2，全量加载（保持现有行为）
- Stage 2 LLM 超时或报错 → 同上降级

## 涉及文件

| 文件 | 改动 |
|------|------|
| `backend/app/skills/models.py` | 加 `embedding vector(1536)` 字段、`category varchar` 字段（预留） |
| `backend/app/skills/seed.py` | seed 时调用 embedding API 生成向量并存 DB |
| `backend/app/agent/router.py` | **新增**：SkillRouter 类，封装 Stage 1 + Stage 2 |
| `backend/app/agent/build.py` | 接入 SkillRouter，替换全量物化逻辑 |
| `backend/app/chat/router.py` | 构造 SkillRouter 实例（注入可配置 LLM）传给 build_agent |

## SkillRouter 接口

```python
class SkillRouter:
    def __init__(self, llm: BaseChatModel, db: AsyncSession, top_k: int = 8, threshold: float = 0.5):
        ...

    async def route(self, user_message: str, user_skills: list[Skill]) -> RoutePlan:
        # Stage 1: embedding 召回
        # Stage 2: LLM 决策
        # 返回 RoutePlan（含 plan steps 或 fallback=True）
        ...
```

## LLM Provider 配置

- Router 接收 `BaseChatModel` 实例，不硬绑 DeepSeek
- 配置项：`ROUTER_LLM_PROVIDER`（env），默认复用 `ChatDeepSeek`
- 未来可替换为任意 LangChain-compatible model

## 分层扩展（预留，100+ skills 时启用）

- `skills` 表的 `category` 字段已预留
- Stage 1 超过 100 个 skill 时，先按 category 过滤再做向量检索
- 无需改动 SkillRouter 接口，只改 Stage 1 内部实现

## 不在本次范围内

- 前端展示 Router 决策过程
- Router 决策结果缓存
- 用户手动覆盖 Router 选择
