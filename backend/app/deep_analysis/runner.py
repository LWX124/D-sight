"""Phase 1 Mock Runner。

只推进阶段、写 mock 结果，不执行任何实际分析。
每个阶段边界检查 cancellation，确保 worker 可以响应取消请求。
所有状态写入都携带 claim_token + lease_version（租约校验）。
"""
import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.credits.models import CreditTransaction
from app.deep_analysis.models import DeepAnalysisReport

STAGES = [
    ("fetching_data", 10),
    ("running_analysts", 40),
    ("assessing_risk", 70),
    ("synthesizing", 85),
    ("finalizing", 95),
]

MOCK_RESULT = {
    "schema_version": "1",
    "mock": True,
    "conclusion": {
        "status": "actionable",
        "action": "hold",
        "confidence": 50,
        "reasoning": "Phase 1 mock runner — no real analysis performed.",
    },
}


async def _is_cancelled(db: AsyncSession, report_id: uuid.UUID) -> bool:
    r = (
        await db.execute(
            select(DeepAnalysisReport.status).where(DeepAnalysisReport.id == report_id)
        )
    ).scalar_one_or_none()
    return r == "cancelled"


async def _update_stage(
    db: AsyncSession,
    report_id: uuid.UUID,
    claim_token: uuid.UUID,
    lease_version: int,
    stage: str,
    progress: int,
) -> bool:
    """更新阶段。返回 False 表示租约已失效（被恢复器或取消覆盖）。"""
    result = await db.execute(
        update(DeepAnalysisReport)
        .where(
            DeepAnalysisReport.id == report_id,
            DeepAnalysisReport.claim_token == claim_token,
            DeepAnalysisReport.lease_version == lease_version,
            DeepAnalysisReport.status == "running",
        )
        .values(stage=stage, progress=progress, heartbeat_at=datetime.now(timezone.utc))
        .returning(DeepAnalysisReport.id)
    )
    await db.commit()
    return result.scalar_one_or_none() is not None


async def run(
    db: AsyncSession,
    report_id: uuid.UUID,
    claim_token: uuid.UUID,
    lease_version: int,
) -> None:
    """执行 mock runner。任何阶段检测到租约失效立即退出。"""
    for stage, progress in STAGES:
        if await _is_cancelled(db, report_id):
            return
        ok = await _update_stage(db, report_id, claim_token, lease_version, stage, progress)
        if not ok:
            return  # 租约失效，退出
        await asyncio.sleep(0.1)  # 模拟工作，Phase 2 替换为实际逻辑

    # 写完成：同一 UPDATE 语句保证 settled_credits 使用实际 reserved 金额
    now = datetime.now(timezone.utc)

    # 先读 reserved_credits（在租约内，当前 session 已有数据）
    report_row = (
        await db.execute(
            select(DeepAnalysisReport.reserved_credits, DeepAnalysisReport.credit_state, DeepAnalysisReport.user_id)
            .where(
                DeepAnalysisReport.id == report_id,
                DeepAnalysisReport.claim_token == claim_token,
                DeepAnalysisReport.lease_version == lease_version,
                DeepAnalysisReport.status == "running",
            )
        )
    ).one_or_none()
    if report_row is None:
        # 租约已失效，退出
        return

    reserved = report_row.reserved_credits
    user_id = report_row.user_id
    credit_state = report_row.credit_state

    result = await db.execute(
        update(DeepAnalysisReport)
        .where(
            DeepAnalysisReport.id == report_id,
            DeepAnalysisReport.claim_token == claim_token,
            DeepAnalysisReport.lease_version == lease_version,
            DeepAnalysisReport.status == "running",
        )
        .values(
            status="completed",
            stage="finalizing",
            progress=100,
            conclusion_status="actionable",
            result=MOCK_RESULT,
            finished_at=now,
            credit_state="settled",
            settled_credits=reserved,
        )
        .returning(DeepAnalysisReport.id)
    )
    updated_id = result.scalar_one_or_none()
    if updated_id is not None and credit_state == "reserved" and reserved > 0:
        # 写 settle 积分流水（差额为 0，预留即结算；生产中可补差价）
        db.add(
            CreditTransaction(
                user_id=user_id,
                kind="settle",
                amount=0,  # reserved 已在 reserve 时扣除，settle 不再重复扣
                balance_after=0,  # 余额不变，amount=0 仅做流水记录
                ref_type="deep_analysis",
                ref_id=str(report_id),
                operation="settle",
            )
        )
    await db.commit()
