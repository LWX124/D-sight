"""CapabilityRouter：门控 → Stage 1 embedding 召回 → Stage 2 LLM 规划。

门控：高置信无工具意图（短寒暄）→ direct_answer，跳过 Stage 1/2。
Stage 1：用 query embedding 与各 capability embedding 余弦相似度召回 top-k。
Stage 2：LLM 基于 candidates 输出结构化 RoutePlan。
任一阶段失败均降级 fallback（全量加载，保持现有行为）。
"""
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

# 短消息（<10 char）且含寒暄词 → 高置信无工具意图
_GATING_KEYWORDS = frozenset([
    "你好", "谢谢", "再见", "在吗", "哈喽", "ok", "好的",
    "hello", "hi", "thanks", "bye", "thx",
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
    mode: str  # single | sequential | parallel
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

        # 无 embedding 的 capability 全文匹配兜底（内置 tools 尚无 embedding）
        no_emb = [c for c in capabilities if not c.embedding]

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[: self._top_k]

        # 候选为空，或最高分仍低于阈值 → fallback
        if not top or top[0][0] < self._threshold:
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
