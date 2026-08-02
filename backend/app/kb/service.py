"""请求内的知识库业务逻辑：查重建行、配额检查。

与 ingest.py 的分工：这里跑在请求的 session 里（快、要事务一致）；ingest.py 跑在
后台任务里（慢、自己开 session）。混在一个文件里容易误用错的 session。
"""
import uuid
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.config import get_settings
from app.kb.models import Kb, KbDocument, KbSource
from app.kb.sources import describe


class QuotaExceeded(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


async def _find_existing(
    db: AsyncSession, kb_id: uuid.UUID, source_type: str, source_ref_id: str
) -> uuid.UUID | None:
    return await db.scalar(
        select(KbDocument.id).where(
            KbDocument.kb_id == kb_id,
            KbDocument.source_type == source_type,
            KbDocument.source_ref_id == source_ref_id,
        )
    )


async def add_source_item(
    db: AsyncSession,
    kb_id: uuid.UUID,
    source_type: str,
    source_ref_id: str,
    kb_source_id: uuid.UUID | None = None,
) -> tuple[Literal["added", "duplicate"], uuid.UUID | None]:
    """建一条 pending 文档行。正文抓取与切片由调用方丢后台。

    duplicate 不是错误——前端提示「已在库中」。source_type 不支持或源不存在时
    抛 SourceNotFound，由调用方转成 4xx / 批量结果里的 failed 项。
    """
    if await _find_existing(db, kb_id, source_type, source_ref_id) is not None:
        return "duplicate", None

    meta = await describe(db, source_type, source_ref_id)
    doc = KbDocument(
        kb_id=kb_id, title=meta.title[:512], filename=None,
        source_type=source_type, source_ref_id=source_ref_id,
        source_url=meta.source_url, published_at=meta.published_at,
        kb_source_id=kb_source_id, status="pending",
    )
    db.add(doc)
    try:
        await db.commit()
    except IntegrityError:
        # 并发窗口：另一请求刚插了同一条。唯一约束兜底，不依赖「先查后插」。
        await db.rollback()
        return "duplicate", None
    return "added", doc.id


async def check_document_quota(db: AsyncSession, kb_id: uuid.UUID, user: User) -> None:
    """单库文档数上限。上传文档也计入——上限管的是库的规模，不是来源。"""
    if user.role == "admin":
        return
    limit = get_settings().kb_max_documents_per_kb
    n = (await db.execute(
        select(func.count()).select_from(KbDocument).where(KbDocument.kb_id == kb_id)
    )).scalar_one()
    if n >= limit:
        raise QuotaExceeded(f"该知识库已达 {limit} 篇文档上限，请先清理或新建知识库")


async def check_source_quota(db: AsyncSession, user: User) -> None:
    """每用户订阅源总数上限（跨其所有知识库统计）。"""
    if user.role == "admin":
        return
    limit = get_settings().kb_max_sources_per_user
    n = (await db.execute(
        select(func.count()).select_from(KbSource)
        .join(Kb, Kb.id == KbSource.kb_id).where(Kb.owner_id == user.id)
    )).scalar_one()
    if n >= limit:
        raise QuotaExceeded(f"已达 {limit} 个订阅源上限，请先断开一些订阅")
