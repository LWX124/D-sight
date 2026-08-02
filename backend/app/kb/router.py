import secrets
import uuid

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile,
)
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.config import get_settings
from app.core.db import get_db
from app.kb.backfill import backfill_source, ingest_source_document
from app.kb.ingest import ingest_document
from app.kb.models import Kb, KbDocument, KbSource, KbSubscription
from app.kb.schemas import (
    DocumentDetailOut, DocumentOut, ItemsIn, ItemsResult, KbCreate, KbOut,
    SourceIn, SourceOut,
)
from app.kb.service import (
    QuotaExceeded, add_source_item, check_document_quota, check_source_quota,
)
from app.kb.sources import SourceNotFound

router = APIRouter(prefix="/api/kb", tags=["kb"])
_ALLOWED = {"txt", "md", "pdf"}


async def _owned_kb(db: AsyncSession, user: User, kb_id: str) -> Kb:
    try:
        kid = uuid.UUID(kb_id)
    except ValueError:
        raise HTTPException(404, "知识库不存在")
    kb = await db.get(Kb, kid)
    if kb is None or kb.owner_id != user.id:
        raise HTTPException(404, "知识库不存在")
    return kb


async def _owned_document(db: AsyncSession, kb: Kb, doc_id: str) -> KbDocument:
    try:
        did = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(404, "文档不存在")
    doc = await db.get(KbDocument, did)
    if doc is None or doc.kb_id != kb.id:
        raise HTTPException(404, "文档不存在")
    return doc


def _doc_out(d: KbDocument) -> dict:
    return {
        "id": str(d.id), "title": d.title, "filename": d.filename, "status": d.status,
        "chunk_count": d.chunk_count, "error": d.error, "source_type": d.source_type,
        "source_url": d.source_url,
        "published_at": d.published_at.isoformat() if d.published_at else None,
    }


def _source_out(s: KbSource) -> dict:
    return {
        "id": str(s.id), "source_type": s.source_type, "source_ref_id": s.source_ref_id,
        "display_name": s.display_name, "status": s.status, "enabled": s.enabled,
        "error": s.error,
        "last_synced_at": s.last_synced_at.isoformat() if s.last_synced_at else None,
    }


@router.post("", response_model=KbOut)
async def create_kb(body: KbCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = Kb(owner_id=user.id, name=body.name)
    db.add(kb)
    await db.commit()
    return {"id": str(kb.id), "name": kb.name, "is_shared": kb.is_shared, "doc_count": 0}


@router.get("", response_model=list[KbOut])
async def list_kb(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kbs = (await db.execute(select(Kb).where(Kb.owner_id == user.id).order_by(Kb.created_at))).scalars().all()
    out = []
    for kb in kbs:
        n = (await db.execute(
            select(func.count()).select_from(KbDocument).where(KbDocument.kb_id == kb.id)
        )).scalar_one()
        out.append({"id": str(kb.id), "name": kb.name, "is_shared": kb.is_shared, "doc_count": n})
    return out


# 注意：/subscribed 与 /subscribe/{share_slug} 必须定义在 /{kb_id} 相关路由之前，
# 否则 "subscribed"/"subscribe" 会被 FastAPI 当作 kb_id 路径参数捕获（按定义序匹配）。
@router.get("/subscribed", response_model=list[dict])
async def subscribed_kb(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kbs = (await db.execute(
        select(Kb).join(KbSubscription, KbSubscription.kb_id == Kb.id)
        .where(KbSubscription.user_id == user.id, Kb.is_shared.is_(True)).order_by(Kb.name)
    )).scalars().all()
    return [{"id": str(k.id), "name": k.name} for k in kbs]


@router.post("/subscribe/{share_slug}")
async def subscribe_kb(share_slug: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = (await db.execute(
        select(Kb).where(Kb.share_slug == share_slug, Kb.is_shared.is_(True))
    )).scalar_one_or_none()
    if kb is None:
        raise HTTPException(404, "分享不存在或已关闭")
    if kb.owner_id == user.id:
        raise HTTPException(400, "不能订阅自己的知识库")
    exists = (await db.execute(
        select(KbSubscription).where(KbSubscription.kb_id == kb.id, KbSubscription.user_id == user.id)
    )).scalar_one_or_none()
    if exists is None:
        db.add(KbSubscription(kb_id=kb.id, user_id=user.id))
        await db.commit()
    return {"kb_id": str(kb.id), "name": kb.name}


@router.post("/{kb_id}/share")
async def share_kb(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await _owned_kb(db, user, kb_id)
    if not kb.share_slug:
        kb.share_slug = secrets.token_hex(8)
    kb.is_shared = True
    await db.commit()
    return {"share_slug": kb.share_slug}


@router.delete("/{kb_id}/share")
async def unshare_kb(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await _owned_kb(db, user, kb_id)
    kb.is_shared = False
    await db.commit()
    return {"shared": False}


@router.post("/{kb_id}/documents")
async def upload_document(
    kb_id: str, background: BackgroundTasks, file: UploadFile = File(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    kb = await _owned_kb(db, user, kb_id)
    try:
        await check_document_quota(db, kb.id, user)
    except QuotaExceeded as e:
        raise HTTPException(409, e.message)
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in _ALLOWED:
        raise HTTPException(400, "仅支持 txt/md/pdf")
    raw = await file.read()
    if len(raw) > get_settings().kb_max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "文件过大")
    doc = KbDocument(kb_id=kb.id, title=file.filename or "unnamed",
                     filename=file.filename or "unnamed",
                     source_type="upload", status="pending")
    db.add(doc)
    await db.commit()
    background.add_task(ingest_document, doc.id, doc.filename, raw)
    return {"document_id": str(doc.id), "status": "pending"}


@router.get("/{kb_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    kb_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    kb = await _owned_kb(db, user, kb_id)
    docs = (await db.execute(
        select(KbDocument).where(KbDocument.kb_id == kb.id)
        # 按原始发布时间倒序（上传文档无此值，NULL 排末尾），同刻用 created_at 兜底
        .order_by(KbDocument.published_at.desc().nullslast(), KbDocument.created_at.desc())
        .limit(limit).offset(offset)
    )).scalars().all()
    return [_doc_out(d) for d in docs]


@router.get("/{kb_id}/documents/{doc_id}", response_model=DocumentDetailOut)
async def get_document(
    kb_id: str, doc_id: str,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    kb = await _owned_kb(db, user, kb_id)
    doc = await _owned_document(db, kb, doc_id)
    # 详情展示入库时的文本快照，不回源重抓：检索命中的就是这份文本，
    # 展示与检索必须一致，否则用户会看到「AI 引用的和我看到的不一样」。
    return {**_doc_out(doc), "text": doc.text}


@router.delete("/{kb_id}/documents/{doc_id}")
async def delete_document(
    kb_id: str, doc_id: str,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    kb = await _owned_kb(db, user, kb_id)
    doc = await _owned_document(db, kb, doc_id)
    await db.delete(doc)          # kb_chunks 靠 FK ondelete=CASCADE 连带删除
    await db.commit()
    return {"deleted": True}


@router.post("/{kb_id}/items", response_model=ItemsResult)
async def add_items(
    kb_id: str, body: ItemsIn, background: BackgroundTasks,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """加入内容，收数组支持批量。

    请求内只做 describe + 建行（纯本地，响应即时）；正文抓取与切片丢后台，前端靠
    文档列表轮询看 pending → ready。failed 只覆盖请求阶段的错误（源不存在等），
    后台失败体现为文档 status="failed"。
    """
    kb = await _owned_kb(db, user, kb_id)
    added = duplicate = 0
    failed: list[dict] = []
    for item in body.items:
        try:
            await check_document_quota(db, kb.id, user)
            result, doc_id = await add_source_item(db, kb.id, item.source_type,
                                                  item.source_ref_id)
        except QuotaExceeded as e:
            failed.append({"source_ref_id": item.source_ref_id, "error": e.message})
            break                 # 触顶后同批剩余的必然也失败，不必逐条试
        except SourceNotFound as e:
            failed.append({"source_ref_id": item.source_ref_id, "error": str(e)})
            continue
        if result == "duplicate":
            duplicate += 1
            continue
        added += 1
        background.add_task(ingest_source_document, doc_id, item.source_type,
                            item.source_ref_id)
    return {"added": added, "duplicate": duplicate, "failed": failed}


@router.post("/{kb_id}/sources", response_model=SourceOut)
async def add_source(
    kb_id: str, body: SourceIn, background: BackgroundTasks,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """整号/信源订阅：建 KbSource 后触发后台回填。重复订阅返回已有记录。"""
    kb = await _owned_kb(db, user, kb_id)
    if body.source_type != "wechat_account":
        raise HTTPException(400, f"不支持的来源类型：{body.source_type}")
    existing = await db.scalar(
        select(KbSource).where(
            KbSource.kb_id == kb.id, KbSource.source_type == body.source_type,
            KbSource.source_ref_id == body.source_ref_id,
        )
    )
    if existing is not None:
        return _source_out(existing)
    try:
        await check_source_quota(db, user)
    except QuotaExceeded as e:
        raise HTTPException(409, e.message)
    src = KbSource(kb_id=kb.id, source_type=body.source_type,
                   source_ref_id=body.source_ref_id, display_name=body.display_name)
    db.add(src)
    await db.commit()
    background.add_task(backfill_source, src.id)
    return _source_out(src)


@router.get("/{kb_id}/sources", response_model=list[SourceOut])
async def list_sources(
    kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    kb = await _owned_kb(db, user, kb_id)
    rows = (await db.execute(
        select(KbSource).where(KbSource.kb_id == kb.id).order_by(KbSource.created_at)
    )).scalars().all()
    return [_source_out(s) for s in rows]


@router.get("/{kb_id}/thread")
async def get_kb_thread(
    kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """取/建该库的常驻会话。照 /api/news/thread 的做法，按 ref_id 区分到库。

    type="kb" 使其不进左侧全局会话列表（见 threads/router.py 的 list_threads）。
    """
    from app.threads.models import Thread

    kb = await _owned_kb(db, user, kb_id)
    thread = await db.scalar(
        select(Thread).where(
            Thread.user_id == user.id, Thread.type == "kb",
            Thread.ref_id == kb.id, Thread.deleted_at.is_(None),
        )
    )
    if thread is None:
        thread = Thread(user_id=user.id, title=f"{kb.name} 对话", type="kb", ref_id=kb.id)
        db.add(thread)
        await db.commit()
        await db.refresh(thread)
    return {"thread_id": str(thread.id)}


@router.delete("/{kb_id}/sources/{source_id}")
async def delete_source(
    kb_id: str, source_id: str, purge: bool = False,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """断开订阅。默认保留已入库文档——知识库语义是「我攒下的资料」，不该因退订而蒸发。"""
    kb = await _owned_kb(db, user, kb_id)
    try:
        sid = uuid.UUID(source_id)
    except ValueError:
        raise HTTPException(404, "订阅不存在")
    src = await db.get(KbSource, sid)
    if src is None or src.kb_id != kb.id:
        raise HTTPException(404, "订阅不存在")
    purged = 0
    if purge:
        purged = (await db.execute(
            select(func.count()).select_from(KbDocument)
            .where(KbDocument.kb_source_id == src.id)
        )).scalar_one()
        await db.execute(delete(KbDocument).where(KbDocument.kb_source_id == src.id))
    await db.delete(src)
    await db.commit()
    return {"deleted": True, "purged": purged}


@router.delete("/{kb_id}")
async def delete_kb(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await _owned_kb(db, user, kb_id)
    await db.delete(kb)
    await db.commit()
    return {"deleted": True}
