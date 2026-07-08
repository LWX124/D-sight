import uuid

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.config import get_settings
from app.core.db import get_db
from app.kb.ingest import ingest_document
from app.kb.models import Kb, KbDocument
from app.kb.schemas import KbCreate, KbOut

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


@router.post("/{kb_id}/documents")
async def upload_document(
    kb_id: str, background: BackgroundTasks, file: UploadFile = File(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    kb = await _owned_kb(db, user, kb_id)
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in _ALLOWED:
        raise HTTPException(400, "仅支持 txt/md/pdf")
    raw = await file.read()
    if len(raw) > get_settings().kb_max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "文件过大")
    doc = KbDocument(kb_id=kb.id, filename=file.filename or "unnamed", status="pending")
    db.add(doc)
    await db.commit()
    background.add_task(ingest_document, doc.id, doc.filename, raw)
    return {"document_id": str(doc.id), "status": "pending"}


@router.get("/{kb_id}/documents")
async def list_documents(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await _owned_kb(db, user, kb_id)
    docs = (await db.execute(
        select(KbDocument).where(KbDocument.kb_id == kb.id).order_by(KbDocument.created_at)
    )).scalars().all()
    return [{"id": str(d.id), "filename": d.filename, "status": d.status,
             "chunk_count": d.chunk_count, "error": d.error} for d in docs]


@router.delete("/{kb_id}")
async def delete_kb(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await _owned_kb(db, user, kb_id)
    await db.delete(kb)
    await db.commit()
    return {"deleted": True}
