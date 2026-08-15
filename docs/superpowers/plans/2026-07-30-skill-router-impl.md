# Skill Router 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Skill Router 动态编排，按设计文档 `2026-07-30-skill-router-design.md` 分 8 个 Task 完成。

**Tech Stack:** Python 3.12、SQLAlchemy asyncpg、pgvector、LangChain BaseChatModel、Alembic

## Global Constraints

- 不修改已有业务逻辑，只追加/扩展
- 每个 Task 完成后验证可导入或运行相关测试
- 不提交代码，完成后由用户决定提交

---

### Task 1：skills 模型加 embedding 字段

**Goal:** 给 `Skill` 加 `embedding Vector(1024)`、`embedding_source_hash`、`tags` 三个字段。

**Files:**
- Modify: `backend/app/skills/models.py`

- [ ] **Step 1: 修改 `models.py`**

在 `from sqlalchemy.dialects.postgresql import JSONB, UUID` 后追加：

```python
from pgvector.sqlalchemy import Vector
from app.kb.models import EMBEDDING_DIM
```

在 `Skill` 类末尾（`updated_at` 之后）追加：

```python
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_source_hash: Mapped[str | None] = mapped_column(String(64))
```

- [ ] **Step 2: 验证**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
python3 -c "from app.skills.models import Skill; print('OK')"
```

---

### Task 2：Alembic migration

**Goal:** 给 `skills` 表加 `tags`、`embedding`、`embedding_source_hash` 列和 HNSW 索引。

**Files:**
- Create: `backend/alembic/versions/<hash>_skill_router_embedding.py`

- [ ] **Step 1: 生成 migration**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
source .venv/bin/activate
alembic revision --autogenerate -m "skill_router_embedding"
```

- [ ] **Step 2: 检查并补全生成文件**

确认 `upgrade()` 含三个 `op.add_column`。在 `upgrade()` 末尾手动追加 HNSW 索引（autogenerate 不生成）：

```python
op.execute(
    "CREATE INDEX ix_skills_embedding ON skills "
    "USING hnsw (embedding vector_cosine_ops) "
    "WHERE embedding IS NOT NULL"
)
```

在 `downgrade()` 开头追加：

```python
op.execute("DROP INDEX IF EXISTS ix_skills_embedding")
```

- [ ] **Step 3: 执行**

```bash
alembic upgrade head
```

Expected: 无报错，`skills` 表存在三个新列和 HNSW 索引。

---

### Task 3：seed.py 扩展（tags + category + 增量 embedding）

**Goal:** 解析 frontmatter 中 `quantSkills.tags` 和 `quantSkills.category`，内容指纹驱动增量 embedding 回填。

**Files:**
- Modify: `backend/app/skills/seed.py`

- [ ] **Step 1: 扩展 `parse_skill_md`**

替换现有 `parse_skill_md` 函数（顶部追加 `import hashlib`）：

```python
def parse_skill_md(text: str, slug: str) -> dict:
    name, description, category, tags = slug, "", "research", []
    m = _FM.match(text)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            fm = {}
        name = fm.get("name", slug) or slug
        description = fm.get("description", "") or ""
        qs = fm.get("quantSkills") or {}
        if isinstance(qs, dict):
            category = qs.get("category", "research") or "research"
            raw_tags = qs.get("tags", [])
            tags = raw_tags if isinstance(raw_tags, list) else []
    return {"name": name, "description": description, "body": text,
            "category": category, "tags": tags}
```

文件顶部追加 `import hashlib` 和 `import yaml`。

- [ ] **Step 2: 扩展 `upsert_skills` 加 embedding 回填**

替换现有 `upsert_skills` 函数：

```python
async def upsert_skills(db: AsyncSession) -> int:
    from app.kb.providers import get_embedding_provider
    embedder = get_embedding_provider()
    root = SKILLS_DATA / "skills"
    count = 0
    to_embed: list[tuple] = []  # (skill_obj, source_text)

    for d in sorted(p for p in root.iterdir() if (p / "SKILL.md").is_file()):
        slug = d.name
        meta = parse_skill_md((d / "SKILL.md").read_text(encoding="utf-8"), slug)
        source_text = meta["description"] + " " + " ".join(meta["tags"])
        source_hash = hashlib.sha256(source_text.encode()).hexdigest()[:16]

        existing = (await db.execute(select(Skill).where(Skill.slug == slug))).scalar_one_or_none()
        if existing is None:
            skill = Skill(
                slug=slug, name=meta["name"], description=meta["description"],
                body=meta["body"], category=meta["category"], tags=meta["tags"],
                model_weight="pro" if slug in PRO_SLUGS else "flash",
                embedding_source_hash=source_hash,
            )
            db.add(skill)
            await db.flush()
            to_embed.append((skill, source_text))
        else:
            existing.name = meta["name"]
            existing.description = meta["description"]
            existing.body = meta["body"]
            existing.category = meta["category"]
            existing.tags = meta["tags"]
            if existing.embedding_source_hash != source_hash:
                existing.embedding_source_hash = source_hash
                to_embed.append((existing, source_text))
        count += 1

    # 增量 embedding 回填
    if to_embed:
        texts = [t for _, t in to_embed]
        try:
            vecs = await embedder.embed(texts)
            for (skill_obj, _), vec in zip(to_embed, vecs):
                skill_obj.embedding = vec
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("skill embedding 失败，降级全文匹配: %s", e)

    await db.flush()
    return count
```

- [ ] **Step 3: 验证**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
python3 -c "from app.skills.seed import upsert_skills; print('OK')"
```

---

### Task 4：capability_registry.py

**Goal:** 定义 Capability 元数据模型，首期注册 skill + 内置 tools。

**Files:**
- Create: `backend/app/agent/capability_registry.py`

- [ ] **Step 1: 创建文件**

```python
"""Capability Registry：统一管理 skill / tool / agent 三类 capability 元数据。

首期只注册 skill（从 DB 读取）和内置 tools（硬编码列表）。
"""
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.skills.models import Skill, UserSkill

CapabilityType = Literal["skill", "tool", "agent"]

BUILTIN_TOOLS = [
    {"id": "web_search", "description": "搜索互联网获取最新信息", "tags": ["search", "web"]},
    {"id": "fetch_page", "description": "抓取网页内容", "tags": ["web", "fetch"]},
    {"id": "stock_quote", "description": "获取股票实时行情", "tags": ["stock", "quote", "market"]},
    {"id": "stock_financials", "description": "获取股票财务数据", "tags": ["stock", "financial", "fundamental"]},
    {"id": "run_python", "description": "执行 Python 代码进行数据分析和计算", "tags": ["code", "analysis", "compute"]},
    {"id": "news_query", "description": "查询新闻资讯", "tags": ["news", "information"]},
    {"id": "wechat_query", "description": "查询微信公众号文章", "tags": ["wechat", "social", "news"]},
    {"id": "fund_arb_query", "description": "查询基金套利数据", "tags": ["fund", "arbitrage"]},
]


@dataclass
class Capability:
    id: str
    type: CapabilityType
    description: str
    tags: list[str] = field(default_factory=list)
    embedding: list[float] | None = None


async def load_user_capabilities(db: AsyncSession, user_id) -> list[Capability]:
    """加载用户可用的全部 capabilities（skill + 内置 tools）。"""
    rows = (await db.execute(
        select(Skill)
        .join(UserSkill, UserSkill.skill_id == Skill.id)
        .where(UserSkill.user_id == user_id, Skill.is_active.is_(True))
    )).scalars().all()

    caps: list[Capability] = []
    for s in rows:
        caps.append(Capability(
            id=s.slug,
            type="skill",
            description=s.description,
            tags=s.tags or [],
            embedding=s.embedding,
        ))
    for t in BUILTIN_TOOLS:
        caps.append(Capability(
            id=t["id"],
            type="tool",
            description=t["description"],
            tags=t["tags"],
        ))
    return caps
```

- [ ] **Step 2: 验证**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
python3 -c "from app.agent.capability_registry import load_user_capabilities; print('OK')"
```

---

### Task 5：router.py（CapabilityRouter）

**Goal:** 实现门控 + Stage 1 embedding 召回 + Stage 2 LLM 规划。

**Files:**
- Create: `backend/app/agent/router.py`

- [ ] **Step 1: 创建文件**

```python
"""CapabilityRouter：门控 → Stage 1 embedding 召回 → Stage 2 LLM 规划。"""
import json
import logging
import math
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.capability_registry import Capability
from app.kb.providers import get_embedding_provider

logger = logging.getLogger(__name__)

_GATING_KEYWORDS = frozenset([
    "你好", "谢谢", "再见", "hello", "hi", "thanks", "bye",
])

_PLANNER_SYSTEM = """你是一个 capability 路由规划器。
根据用户消息和候选 capabilities，输出 JSON 执行计划。

输出格式（严格 JSON，不加 markdown 代码块）：
{
  "plan": [
    {"step": 1, "capabilities": ["cap-id"], "mode": "single"},
    {"step": 2, "capabilities": ["cap-a", "cap-b"], "mode": "parallel", "depends_on": [1]}
  ],
  "direct_answer": false,
  "fallback": false
}

mode 枚举：single | sequential | parallel
- 无工具意图时：{"plan": [], "direct_answer": true, "fallback": false}
- 无法判断时：{"plan": [], "direct_answer": false, "fallback": true}
只输出 JSON，不加任何解释。"""


@dataclass
class RouteStep:
    step: int
    capabilities: list[str]
    mode: str
    depends_on: list[int] = field(default_factory=list)


@dataclass
class RoutePlan:
    plan: list[RouteStep] = field(default_factory=list)
    direct_answer: bool = False
    fallback: bool = False


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def _is_direct(message: str) -> bool:
    msg = message.strip().lower()
    if len(msg) < 10 and any(kw in msg for kw in _GATING_KEYWORDS):
        return True
    return False


class CapabilityRouter:
    def __init__(
        self,
        llm: BaseChatModel,
        db: AsyncSession,
        top_k: int = 8,
        threshold: float = 0.5,
    ):
        self._llm = llm
        self._db = db
        self._top_k = top_k
        self._threshold = threshold

    async def route(self, user_message: str, capabilities: list[Capability]) -> RoutePlan:
        # 门控
        if _is_direct(user_message):
            return RoutePlan(direct_answer=True)

        # Stage 1: embedding 召回
        embedder = get_embedding_provider()
        try:
            [query_vec] = await embedder.embed([user_message])
        except Exception as e:
            logger.warning("Router Stage 1 embedding 失败，降级 fallback: %s", e)
            return RoutePlan(fallback=True)

        scored: list[tuple[float, Capability]] = []
        for cap in capabilities:
            if cap.embedding:
                sim = _cosine(query_vec, cap.embedding)
                scored.append((sim, cap))

        # 无 embedding 的 capability 全文匹配兜底
        no_emb = [c for c in capabilities if not c.embedding]

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[: self._top_k]

        if top and top[0][0] < self._threshold:
            return RoutePlan(fallback=True)

        candidates = [cap for _, cap in top] + no_emb[: max(0, self._top_k - len(top))]

        # Stage 2: LLM 规划
        cap_list = "\n".join(
            f"- {c.id} ({c.type}): {c.description} [tags: {', '.join(c.tags)}]"
            for c in candidates
        )
        user_prompt = f"用户消息：{user_message}\n\n可用 capabilities：\n{cap_list}"
        try:
            resp = await self._llm.ainvoke([
                SystemMessage(content=_PLANNER_SYSTEM),
                HumanMessage(content=user_prompt),
            ])
            raw = resp.content.strip()
            data = json.loads(raw)
            steps = [
                RouteStep(
                    step=s["step"],
                    capabilities=s["capabilities"],
                    mode=s.get("mode", "single"),
                    depends_on=s.get("depends_on", []),
                )
                for s in data.get("plan", [])
            ]
            return RoutePlan(
                plan=steps,
                direct_answer=data.get("direct_answer", False),
                fallback=data.get("fallback", False),
            )
        except Exception as e:
            logger.warning("Router Stage 2 LLM 失败，降级 fallback: %s", e)
            return RoutePlan(fallback=True)
```

- [ ] **Step 2: 验证**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
python3 -c "from app.agent.router import CapabilityRouter; print('OK')"
```

---

### Task 6：orchestrator.py（纯同步物化）

**Goal:** 按 RoutePlan 选择要物化的 skill，纯同步调用 `write_skills`。

> `build_agent` 是同步函数，物化只需按 plan 过滤 `skill_rows` 再调 `write_skills`，不碰 DB，故 orchestrator 为纯同步。

**Files:**
- Create: `backend/app/agent/orchestrator.py`

- [ ] **Step 1: 创建文件**

```python
"""DAG Orchestrator：按 RoutePlan 选择并物化 skill 到 workspace/skills/。

纯同步：build_agent 是同步函数，物化只过滤 skill_rows 调 write_skills。
- fallback：全量物化（保持现有行为）
- direct_answer：不物化任何 skill
- 正常 plan：只物化 plan 中出现的 skill slug
tool 类型 capability 由 build_agent 的 tools 列表处理，不在此物化。
"""
import logging
from pathlib import Path

from app.agent.router import RoutePlan
from app.skills.materialize import write_skills

logger = logging.getLogger(__name__)


def materialize_plan(
    plan: RoutePlan,
    workspace: Path,
    skill_rows: list,
) -> list[str]:
    """将 plan 涉及的 skill 物化到 workspace/skills/，返回物化的 slug 列表。"""
    if plan.direct_answer:
        return []

    if plan.fallback:
        write_skills(workspace, skill_rows)
        return [r.slug for r in skill_rows]

    # 收集 plan 中所有 capability id，匹配 skill_rows 中的 slug
    wanted: set[str] = set()
    for step in plan.plan:
        wanted.update(step.capabilities)

    selected = [r for r in skill_rows if r.slug in wanted]
    if selected:
        write_skills(workspace, selected)
        logger.info("Router 物化 %d skills: %s", len(selected), [r.slug for r in selected])
        return [r.slug for r in selected]
    # plan 非空但无匹配 skill（全是 tool capability）：物化空集
    return []
```

- [ ] **Step 2: 验证**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
python3 -c "from app.agent.orchestrator import materialize_plan; print('OK')"
```

---

### Task 7：接入 build.py 和 chat/router.py

**Goal:** `build_agent` 接受可选 `route_plan`；`chat/router.py` 构造 Router 并调用。

**Files:**
- Modify: `backend/app/agent/build.py`
- Modify: `backend/app/chat/router.py`

- [ ] **Step 1: 在 `build.py` 加 `make_router_llm` 工厂**

在 `make_checkpointer` 函数之前追加：

```python
def make_router_llm():
    """Router 用的 LLM，复用主模型配置（首期）。"""
    return _make_model()
```

- [ ] **Step 2: 修改 `build_agent` 签名和物化逻辑**

签名改为：

```python
def build_agent(thread_id: str, checkpointer=None, skill_rows=None, kb_ids=None, user_id=None, route_plan=None):
```

将现有的：

```python
    if skill_rows is not None:
        from app.skills.materialize import write_skills

        write_skills(ws, skill_rows)
```

替换为：

```python
    if skill_rows is not None:
        from app.agent.orchestrator import materialize_plan

        if route_plan is not None:
            materialize_plan(route_plan, ws, skill_rows)
        else:
            from app.skills.materialize import write_skills
            write_skills(ws, skill_rows)
```

- [ ] **Step 3: 修改 `chat/router.py` 注入 Router**

在 `skill_rows = await load_installed_skills(db, user.id)` 之后插入：

```python
    # Skill Router 动态规划
    route_plan = None
    try:
        from app.agent.build import make_router_llm
        from app.agent.capability_registry import load_user_capabilities
        from app.agent.router import CapabilityRouter

        caps = await load_user_capabilities(db, user.id)
        if caps and first_text:
            router = CapabilityRouter(llm=make_router_llm(), db=db)
            route_plan = await router.route(first_text, caps)
    except Exception as _re:
        logger.warning("CapabilityRouter 失败，降级全量加载: %s", _re)
```

将 `build_agent(...)` 调用改为：

```python
    agent = build_agent(
        thread_id, checkpointer, skill_rows=skill_rows, kb_ids=mounted,
        user_id=user.id, route_plan=route_plan,
    )
```

- [ ] **Step 4: 验证导入**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
python3 -c "from app.agent.build import build_agent, make_router_llm; from app.chat.router import router; print('OK')"
```

---

### Task 8：checkpoint state 清除（skills_metadata 问题）

**Goal:** 让 deepagents 每轮重新扫描 workspace/skills，不因 checkpoint 缓存 `skills_metadata` 而复用首轮元数据。

> **实测结论（已落地）**：原计划设想的 `aupdate_state(config, {"skills_metadata": []})` 无效——基类 middleware 在 `"skills_metadata" in state` 时直接 `return None`（skills.py:960），空 list 也算"已存在"，跳过重扫。`None` 同理。最终方案：**子类化 `SkillsMiddleware`，在 `abefore_agent` 委托基类前先 `state.pop("skills_metadata", None)`**，强制每轮重扫。已并入 Task 7 的 `build.py`（`ReloadingSkillsMiddleware` + `middleware=` 注入替代 `skills=`）。

**Files:**
- Modify: `backend/app/agent/build.py`（已在 Task 7 完成实现，本 Task 为验证）

- [x] **Step 1: 实测 aupdate_state 对 PrivateStateAttr 的行为**（结论：无效，见上）

- [x] **Step 2: 子类化方案实现**（已在 Task 7 落地：`ReloadingSkillsMiddleware`）

- [x] **Step 3: 端到端验证跨轮切换**

实测脚本（首轮物化 skill-a、第二轮物化 skill-b，验证第二轮 system prompt 注入 skill-b）：
```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
# FAKE_LLM=1 python3 <script> → t1: ['skill-a']  t2: ['skill-b']
```
结论：第二轮 `skills_metadata` 正确切换为 skill-b，证明 Router 动态选择跨轮生效。

---

## 完成检查单

- [ ] `alembic upgrade head` 无报错，`skills` 表存在 `embedding`、`tags`、`embedding_source_hash` 列
- [ ] `python3 -c "from app.agent.router import CapabilityRouter; print('OK')"` 通过
- [ ] `python3 -c "from app.chat.router import router; print('OK')"` 通过
- [ ] 发送寒暄消息（"你好"），日志显示 `direct_answer=True`，无 skill 物化
- [ ] 发送投研请求，日志显示 Router 物化了相关 skill，而非全量
- [ ] 发送无匹配请求，日志显示 `fallback=True`，全量加载（行为与改前一致）
