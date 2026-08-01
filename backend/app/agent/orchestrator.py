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
        write_skills(workspace, [])
        return []

    if plan.fallback:
        write_skills(workspace, skill_rows)
        return [r.slug for r in skill_rows]

    # 收集 plan 中所有 capability id，匹配 skill_rows 中的 slug
    wanted: set[str] = set()
    for step in plan.plan:
        wanted.update(step.capabilities)

    selected = [r for r in skill_rows if r.slug in wanted]
    write_skills(workspace, selected)
    if selected:
        logger.info("Router 物化 %d skills: %s", len(selected), [r.slug for r in selected])
    return [r.slug for r in selected]
