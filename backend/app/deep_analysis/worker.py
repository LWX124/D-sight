"""深度分析 Worker 进程。

启动方式：
  python -m app.deep_analysis.worker

检查列表（全部满足才启动）：
  - DEEP_ANALYSIS_WORKER_ENABLED=true
  - 数据库连接正常
  - 必需配置非空

Worker 包含两个协程：
  - claim_loop：轮询 pending/retry_wait，认领并执行报告
  - maintenance_loop：恢复失联任务、释放过期积分
"""
import asyncio
import logging
import os
import signal
import socket
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.credits.models import CreditAccount, CreditTransaction
from app.deep_analysis.models import DeepAnalysisReport

logger = logging.getLogger(__name__)

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"
HEARTBEAT_INTERVAL = 15       # 秒
STALE_THRESHOLD = 60          # 秒，超过此值视为失联
MAINTENANCE_INTERVAL = 30     # 秒
CLAIM_SLEEP = 2               # 无任务时等待
GRACE_PERIOD = 120            # SIGTERM 后最多等待秒数

_stop = asyncio.Event()
_active: set[asyncio.Task] = set()


def _make_session() -> async_sessionmaker:
    settings = get_settings()
    # worker 专用 engine，独立连接池，避免与 API 共享。
    engine = create_async_engine(settings.database_url, pool_size=5, max_overflow=2)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _claim_one(Session: async_sessionmaker) -> tuple[uuid.UUID, uuid.UUID, int] | None:
    """认领一条 pending/retry_wait 报告，返回 (report_id, claim_token, lease_version)。"""
    now = datetime.now(timezone.utc)
    new_token = uuid.uuid4()

    async with Session() as db:
        async with db.begin():
            row = (
                await db.execute(
                    select(DeepAnalysisReport)
                    .where(
                        DeepAnalysisReport.status.in_(("pending", "retry_wait")),
                        DeepAnalysisReport.next_retry_at <= now,
                    )
                    .order_by(
                        DeepAnalysisReport.next_retry_at, DeepAnalysisReport.created_at
                    )
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()

            if row is None:
                return None

            new_version = row.lease_version + 1
            row.status = "running"
            row.worker_id = WORKER_ID
            row.claim_token = new_token
            row.lease_version = new_version
            row.heartbeat_at = now
            row.started_at = row.started_at or now
            row.attempt_count += 1
            return row.id, new_token, new_version


async def _heartbeat(
    Session: async_sessionmaker,
    report_id: uuid.UUID,
    token: uuid.UUID,
    version: int,
) -> None:
    """每 HEARTBEAT_INTERVAL 秒更新心跳。心跳失败不中断主任务。"""
    while not _stop.is_set():
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        try:
            async with Session() as db:
                async with db.begin():
                    await db.execute(
                        update(DeepAnalysisReport)
                        .where(
                            DeepAnalysisReport.id == report_id,
                            DeepAnalysisReport.claim_token == token,
                            DeepAnalysisReport.lease_version == version,
                            DeepAnalysisReport.status == "running",
                        )
                        .values(heartbeat_at=datetime.now(timezone.utc))
                    )
        except Exception as e:  # noqa: BLE001
            logger.warning("heartbeat failed report=%s: %s", report_id, e)


async def _release_credits(db: AsyncSession, row: DeepAnalysisReport) -> None:
    """在已持有行锁的事务内退还积分并写 release 流水。"""
    if row.credit_state != "reserved" or row.reserved_credits <= 0:
        return
    acct = (
        await db.execute(
            select(CreditAccount)
            .where(CreditAccount.user_id == row.user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if acct is not None:
        acct.balance += row.reserved_credits
        db.add(
            CreditTransaction(
                user_id=row.user_id,
                kind="refund",
                amount=row.reserved_credits,
                balance_after=acct.balance,
                ref_type="deep_analysis",
                ref_id=str(row.id),
                operation="release",
            )
        )
    row.credit_state = "released"


async def _mark_retry_or_failed(
    Session: async_sessionmaker,
    report_id: uuid.UUID,
    token: uuid.UUID,
    version: int,
    error_msg: str,
) -> None:
    now = datetime.now(timezone.utc)
    async with Session() as db:
        async with db.begin():
            row = (
                await db.execute(
                    select(DeepAnalysisReport)
                    .where(
                        DeepAnalysisReport.id == report_id,
                        DeepAnalysisReport.claim_token == token,
                        DeepAnalysisReport.lease_version == version,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                return  # 已被恢复器处理
            if row.attempt_count >= row.max_attempts:
                row.status = "failed"
                row.finished_at = now
                row.error_message = error_msg
                row.error_code = "max_attempts_exceeded"
                await _release_credits(db, row)  # 退还积分并写 release 流水
            else:
                backoff = min(60 * (2 ** (row.attempt_count - 1)), 300)
                row.status = "retry_wait"
                row.next_retry_at = now + timedelta(seconds=backoff)
                row.error_message = error_msg


async def _execute(
    Session: async_sessionmaker,
    report_id: uuid.UUID,
    token: uuid.UUID,
    version: int,
) -> None:
    """执行报告（Phase 1 调 mock runner）。失败写 retry_wait 或 failed。"""
    from app.deep_analysis.runner import run

    hb = asyncio.create_task(_heartbeat(Session, report_id, token, version))
    try:
        async with Session() as db:
            await run(db, report_id, token, version)
        logger.info("report completed report=%s", report_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("report failed report=%s: %s", report_id, e)
        await _mark_retry_or_failed(Session, report_id, token, version, str(e))
    finally:
        hb.cancel()


async def _recover_stale(Session: async_sessionmaker) -> None:
    """将心跳超时的 running 报告转为 retry_wait/failed。"""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STALE_THRESHOLD)
    async with Session() as db:
        async with db.begin():
            rows = (
                await db.execute(
                    select(DeepAnalysisReport)
                    .where(
                        DeepAnalysisReport.status == "running",
                        DeepAnalysisReport.heartbeat_at < cutoff,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(10)
                )
            ).scalars().all()

            now = datetime.now(timezone.utc)
            for row in rows:
                if row.attempt_count >= row.max_attempts:
                    row.status = "failed"
                    row.finished_at = now
                    row.error_code = "worker_lost"
                    await _release_credits(db, row)  # 退还积分并写 release 流水
                else:
                    row.status = "retry_wait"
                    row.next_retry_at = now + timedelta(seconds=30)
                row.worker_id = None
                row.claim_token = None
    if rows:
        logger.info("recovered %d stale reports", len(rows))


async def claim_loop(Session: async_sessionmaker) -> None:
    while not _stop.is_set():
        try:
            claimed = await _claim_one(Session)
            if claimed is not None:
                report_id, token, version = claimed
                task = asyncio.create_task(_execute(Session, report_id, token, version))
                _active.add(task)
                task.add_done_callback(_active.discard)
            else:
                await asyncio.sleep(CLAIM_SLEEP)
        except Exception as e:  # noqa: BLE001
            logger.exception("claim_loop error: %s", e)
            await asyncio.sleep(CLAIM_SLEEP)


async def maintenance_loop(Session: async_sessionmaker) -> None:
    while not _stop.is_set():
        try:
            await _recover_stale(Session)
        except Exception as e:  # noqa: BLE001
            logger.exception("maintenance_loop error: %s", e)
        await asyncio.sleep(MAINTENANCE_INTERVAL)


async def main() -> None:
    settings = get_settings()
    if not settings.deep_analysis_worker_enabled:
        logger.error("DEEP_ANALYSIS_WORKER_ENABLED is false, refusing to start")
        return

    logging.basicConfig(level=logging.INFO)
    logger.info("worker starting worker_id=%s", WORKER_ID)

    Session = _make_session()

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, _stop.set)
    loop.add_signal_handler(signal.SIGINT, _stop.set)

    tasks = [
        asyncio.create_task(claim_loop(Session)),
        asyncio.create_task(maintenance_loop(Session)),
    ]
    await _stop.wait()
    logger.info("worker shutting down, waiting for active tasks...")

    for t in tasks:
        t.cancel()
    if _active:
        await asyncio.wait(list(_active), timeout=GRACE_PERIOD)
    logger.info("worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
