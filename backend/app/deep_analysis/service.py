"""深度分析 Service 层。

create_report：
  1. 幂等键重放检查（相同 key + 相同 fingerprint → 返回原报告）
  2. 完成缓存命中检查（4h 内同 market/ticker/version → 返回缓存）
  3. 活跃任务去重（pending/running/retry_wait 已存在 → deduplicated）
  4. 积分余额检查
  5. 原子事务：创建报告 + 写 reserve 积分流水
"""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.credits.models import CreditAccount, CreditTransaction
from app.credits.service import InsufficientCredits
from app.deep_analysis.models import DeepAnalysisReport

ACTIVE_STATUSES = ("pending", "running", "retry_wait")
DEEP_ANALYSIS_CREDITS = 50


class IdempotencyFingerprintMismatch(Exception):
    """相同 idempotency_key 但请求指纹不同，应返回 409。"""


def _fingerprint(market: str, normalized_ticker: str, version: str) -> str:
    raw = f"{market}:{normalized_ticker}:{version}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _normalize_ticker(market: str, ticker: str) -> str:
    """Phase 1 只做基础规范化；Phase 2 扩展为完整校验。"""
    t = ticker.strip().upper()
    if market == "A":
        # 去掉可能的 SH/SZ 前缀，取 6 位数字
        digits = "".join(ch for ch in t if ch.isdigit())
        digits = digits.zfill(6)[-6:]
        if digits.startswith("6"):
            return f"{digits}.SH"
        return f"{digits}.SZ"
    if market == "HK":
        digits = "".join(ch for ch in t if ch.isdigit())
        digits = digits.lstrip("0") or "0"
        return f"{digits.zfill(4)}.HK"
    return t  # US: uppercase as-is


def _cache_hours() -> int:
    return getattr(get_settings(), "deep_analysis_cache_hours", 4)


def _credits_price() -> int:
    return getattr(get_settings(), "deep_analysis_credits", 50)


def _analysis_version() -> str:
    return getattr(get_settings(), "deep_analysis_analysis_version", "v1")


async def create_report(
    db: AsyncSession,
    user_id: uuid.UUID,
    market: str,
    ticker: str,
    idempotency_key: str | None,
    is_admin: bool = False,
) -> tuple[DeepAnalysisReport, bool, bool]:
    """返回 (report, cache_hit, deduplicated)。调用方负责提交事务。"""
    version = _analysis_version()
    normalized = _normalize_ticker(market, ticker)
    fp = _fingerprint(market, normalized, version)
    now = datetime.now(timezone.utc)

    # 1. 幂等键重放（过滤软删除：deleted_at IS NULL）
    if idempotency_key:
        existing = (
            await db.execute(
                select(DeepAnalysisReport).where(
                    DeepAnalysisReport.user_id == user_id,
                    DeepAnalysisReport.idempotency_key == idempotency_key,
                    DeepAnalysisReport.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.request_fingerprint != fp:
                raise IdempotencyFingerprintMismatch(
                    "idempotency_key 已绑定不同请求指纹"
                )
            return existing, existing.status == "completed", False

    # 2. 完成缓存命中
    cache_cutoff = now - timedelta(hours=_cache_hours())
    cached = (
        await db.execute(
            select(DeepAnalysisReport).where(
                DeepAnalysisReport.user_id == user_id,
                DeepAnalysisReport.market == market,
                DeepAnalysisReport.normalized_ticker == normalized,
                DeepAnalysisReport.analysis_version == version,
                DeepAnalysisReport.status == "completed",
                DeepAnalysisReport.deleted_at.is_(None),
                DeepAnalysisReport.finished_at >= cache_cutoff,
            )
        )
    ).scalar_one_or_none()
    if cached is not None:
        return cached, True, False

    # 3. 活跃任务去重
    active = (
        await db.execute(
            select(DeepAnalysisReport).where(
                DeepAnalysisReport.user_id == user_id,
                DeepAnalysisReport.market == market,
                DeepAnalysisReport.normalized_ticker == normalized,
                DeepAnalysisReport.analysis_version == version,
                DeepAnalysisReport.status.in_(ACTIVE_STATUSES),
                DeepAnalysisReport.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if active is not None:
        return active, False, True

    # 4. 积分检查（非管理员）
    credits_to_reserve = 0 if is_admin else _credits_price()
    tx_ref: CreditTransaction | None = None
    if not is_admin:
        acct = (
            await db.execute(
                select(CreditAccount)
                .where(CreditAccount.user_id == user_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if acct is None or acct.balance < credits_to_reserve:
            raise InsufficientCredits()
        acct.balance -= credits_to_reserve
        tx_ref = CreditTransaction(
            user_id=user_id,
            kind="charge",
            amount=-credits_to_reserve,
            balance_after=acct.balance,
            ref_type="deep_analysis",
            ref_id=None,  # 先 flush 再回填
            operation="reserve",
        )
        db.add(tx_ref)

    # 5. 创建报告
    report = DeepAnalysisReport(
        user_id=user_id,
        market=market,
        ticker=ticker,
        normalized_ticker=normalized,
        analysis_version=version,
        status="pending",
        idempotency_key=idempotency_key,
        request_fingerprint=fp,
        credit_state="exempt" if is_admin else "reserved",
        reserved_credits=credits_to_reserve,
    )
    db.add(report)
    await db.flush()  # 获取 report.id

    # 回填积分流水的 ref_id
    if tx_ref is not None:
        tx_ref.ref_id = str(report.id)

    await db.flush()
    return report, False, False
