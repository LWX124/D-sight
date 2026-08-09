"""Capability Registry：统一管理 skill / tool / agent 三类 capability 元数据。

首期只注册 skill（从 DB 读取）和内置 tools（硬编码列表）。
"""
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.skills.models import Skill, UserSkill

CapabilityType = Literal["skill", "tool", "agent"]

# 与 app/agent/build.py 的 tools 列表对应（id 即 LLM 可见的工具名）。
BUILTIN_TOOLS = [
    {"id": "web_search", "description": "搜索互联网获取最新信息", "tags": ["search", "web"]},
    {"id": "fetch_page", "description": "抓取网页内容", "tags": ["web", "fetch"]},
    {"id": "stock_quote", "description": "获取股票实时行情", "tags": ["stock", "quote", "market"]},
    {"id": "stock_financials", "description": "获取股票财务数据", "tags": ["stock", "financial", "fundamental"]},
    {"id": "run_python", "description": "执行 Python 代码进行数据分析和计算", "tags": ["code", "analysis", "compute"]},
    {"id": "news_query", "description": "查询新闻资讯", "tags": ["news", "information"]},
    {"id": "wechat_query", "description": "查询微信公众号文章", "tags": ["wechat", "social", "news"]},
    {"id": "weibo_query", "description": "查询当前用户订阅的微博内容快照", "tags": ["weibo", "social", "news"]},
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
