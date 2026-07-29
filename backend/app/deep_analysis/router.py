"""深度分析 HTTP 路由。

路由只做：鉴权、参数校验、调用 service、返回响应。
不含业务编排逻辑。
所有单报告操作均验证 report.user_id == current_user.id，
不命中一律 404，不暴露他人报告存在性。
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.db import get_db
from app.credits.models import CreditAccount, CreditTransaction
from app.credits.service import InsufficientCredits
from app.deep_analysis.models import DeepAnalysisReport
from app.deep_analysis.schemas import (
    DeepAnalysisCreateRequest,
    DeepAnalysisCreateResponse,
    DeepAnalysisListResponse,
    DeepAnalysisStatusResponse,
)
from app.deep_analysis.service import IdempotencyFingerprintMismatch, create_report

router = APIRouter(prefix="/api/deep-analysis", tags=["deep-analysis"])

ACTIVE_STATUSES = ("pending", "running", "retry_wait")


def _to_status(r: DeepAnalysisReport) -> DeepAnalysisStatusResponse:
    return DeepAnalysisStatusResponse(
        id=r.id,
        market=r.market,
        ticker=r.ticker,
        normalized_ticker=r.normalized_ticker,
        status=r.status,
        stage=r.stage,
        progress=r.progress,
        attempt_count=r.attempt_count,
        conclusion_status=r.conclusion_status,
        result=r.result,
        error_code=r.error_code,
        error_message=r.error_message,
        created_at=r.created_at,
        started_at=r.started_at,
        finished_at=r.finished_at,
    )


@router.post("", response_model=DeepAnalysisCreateResponse, status_code=202)
async def create(
    body: DeepAnalysisCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    is_admin = current_user.role == "admin"
    try:
        report, cache_hit, deduplicated = await create_report(
            db,
            user_id=current_user.id,
            market=body.market,
            ticker=body.ticker,
            idempotency_key=body.idempotency_key,
            is_admin=is_admin,
        )
        await db.commit()
    except InsufficientCredits:
        await db.rollback()
        raise HTTPException(status_code=402, detail="积分不足")
    except IdempotencyFingerprintMismatch:
        await db.rollback()
        raise HTTPException(status_code=409, detail="idempotency_key 已绑定不同请求")
    except IntegrityError:
        # 并发请求同时通过去重检查并竞争 INSERT，唯一约束冲突。
        # 退出当前事务后重新查询已存在的活跃任务返回给调用方。
        await db.rollback()
        from sqlalchemy import select as _sel
        from app.deep_analysis.service import _normalize_ticker, _analysis_version
        normalized = _normalize_ticker(body.market, body.ticker)
        version = _analysis_version()
        active = (
            await db.execute(
                _sel(DeepAnalysisReport).where(
                    DeepAnalysisReport.user_id == current_user.id,
                    DeepAnalysisReport.market == body.market,
                    DeepAnalysisReport.normalized_ticker == normalized,
                    DeepAnalysisReport.analysis_version == version,
                    DeepAnalysisReport.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if active is None:
            raise HTTPException(status_code=500, detail="内部错误，请重试")
        return DeepAnalysisCreateResponse(
            id=active.id,
            status=active.status,
            cache_hit=False,
            deduplicated=True,
            reserved_credits=active.reserved_credits,
        )

    return DeepAnalysisCreateResponse(
        id=report.id,
        status=report.status,
        cache_hit=cache_hit,
        deduplicated=deduplicated,
        reserved_credits=report.reserved_credits,
    )


@router.get("/{report_id}", response_model=DeepAnalysisStatusResponse)
async def get_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = (
        await db.execute(
            select(DeepAnalysisReport).where(
                DeepAnalysisReport.id == report_id,
                DeepAnalysisReport.user_id == current_user.id,
                DeepAnalysisReport.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return _to_status(report)


@router.get("", response_model=DeepAnalysisListResponse)
async def list_reports(
    market: str | None = Query(default=None),
    status: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conditions = [
        DeepAnalysisReport.user_id == current_user.id,
        DeepAnalysisReport.deleted_at.is_(None),
    ]
    if market:
        conditions.append(DeepAnalysisReport.market == market)
    if status:
        conditions.append(DeepAnalysisReport.status == status)
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            conditions.append(DeepAnalysisReport.created_at < cursor_dt)
        except ValueError:
            raise HTTPException(status_code=422, detail="cursor 格式无效")

    rows = (
        await db.execute(
            select(DeepAnalysisReport)
            .where(and_(*conditions))
            .order_by(DeepAnalysisReport.created_at.desc())
            .limit(limit + 1)
        )
    ).scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1].created_at.isoformat() if has_more and items else None
    return DeepAnalysisListResponse(
        items=[_to_status(r) for r in items], next_cursor=next_cursor
    )


@router.post("/{report_id}/cancel", response_model=DeepAnalysisStatusResponse)
async def cancel_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = (
        await db.execute(
            select(DeepAnalysisReport)
            .where(
                DeepAnalysisReport.id == report_id,
                DeepAnalysisReport.user_id == current_user.id,
                DeepAnalysisReport.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    if report.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="当前状态不可取消")
    report.status = "cancelled"
    report.cancelled_at = datetime.now(timezone.utc)
    # 释放积分（reserved → released）
    if report.credit_state == "reserved" and report.reserved_credits > 0:
        acct = (
            await db.execute(
                select(CreditAccount)
                .where(CreditAccount.user_id == current_user.id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if acct is not None:
            acct.balance += report.reserved_credits
            db.add(
                CreditTransaction(
                    user_id=current_user.id,
                    kind="refund",
                    amount=report.reserved_credits,
                    balance_after=acct.balance,
                    ref_type="deep_analysis",
                    ref_id=str(report.id),
                    operation="release",
                )
            )
        report.credit_state = "released"
    await db.commit()
    return _to_status(report)


@router.delete("/{report_id}", status_code=204)
async def delete_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = (
        await db.execute(
            select(DeepAnalysisReport)
            .where(
                DeepAnalysisReport.id == report_id,
                DeepAnalysisReport.user_id == current_user.id,
                DeepAnalysisReport.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    if report.status in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="请先取消运行中的任务再删除")
    report.deleted_at = datetime.now(timezone.utc)
    report.deleted_by = current_user.id
    # 清空幂等键，允许用户用同一 key 创建新报告
    report.idempotency_key = None
    await db.commit()
    return None
