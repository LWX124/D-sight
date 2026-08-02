import uuid

import pytest

from app.auth.models import User
from app.core import config
from app.core.security import hash_password
from app.kb.models import Kb, KbDocument, KbSource
from app.kb.service import (
    QuotaExceeded,
    check_document_quota,
    check_source_quota,
)


async def _user(db, role="user"):
    u = User(email=f"q-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"), role=role)
    db.add(u)
    await db.flush()
    return u


@pytest.fixture
def tiny_limits(monkeypatch):
    monkeypatch.setenv("KB_MAX_DOCUMENTS_PER_KB", "2")
    monkeypatch.setenv("KB_MAX_SOURCES_PER_USER", "1")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_document_quota_blocks_normal_user(db_session, tiny_limits):
    u = await _user(db_session)
    kb = Kb(owner_id=u.id, name="满库")
    db_session.add(kb)
    await db_session.flush()
    for i in range(2):
        db_session.add(KbDocument(kb_id=kb.id, title=f"d{i}", filename=f"d{i}.txt",
                                  source_type="upload", status="ready"))
    await db_session.commit()
    with pytest.raises(QuotaExceeded) as e:
        await check_document_quota(db_session, kb.id, u)
    assert "2 篇文档上限" in e.value.message


@pytest.mark.asyncio
async def test_document_quota_exempts_admin(db_session, tiny_limits):
    admin = await _user(db_session, role="admin")
    kb = Kb(owner_id=admin.id, name="管理员库")
    db_session.add(kb)
    await db_session.flush()
    for i in range(5):
        db_session.add(KbDocument(kb_id=kb.id, title=f"a{i}", filename=f"a{i}.txt",
                                  source_type="upload", status="ready"))
    await db_session.commit()
    await check_document_quota(db_session, kb.id, admin)   # 不抛


@pytest.mark.asyncio
async def test_document_quota_passes_under_limit(db_session, tiny_limits):
    u = await _user(db_session)
    kb = Kb(owner_id=u.id, name="空库")
    db_session.add(kb)
    await db_session.commit()
    await check_document_quota(db_session, kb.id, u)       # 不抛


@pytest.mark.asyncio
async def test_source_quota_counts_across_user_kbs(db_session, tiny_limits):
    u = await _user(db_session)
    kb = Kb(owner_id=u.id, name="订阅库")
    db_session.add(kb)
    await db_session.flush()
    db_session.add(KbSource(kb_id=kb.id, source_type="wechat_account",
                            source_ref_id=str(uuid.uuid4()), display_name="号1"))
    await db_session.commit()
    with pytest.raises(QuotaExceeded) as e:
        await check_source_quota(db_session, u)
    assert "1 个订阅源上限" in e.value.message


@pytest.mark.asyncio
async def test_source_quota_exempts_admin(db_session, tiny_limits):
    admin = await _user(db_session, role="admin")
    kb = Kb(owner_id=admin.id, name="k")
    db_session.add(kb)
    await db_session.flush()
    for i in range(3):
        db_session.add(KbSource(kb_id=kb.id, source_type="wechat_account",
                                source_ref_id=str(uuid.uuid4()), display_name=f"号{i}"))
    await db_session.commit()
    await check_source_quota(db_session, admin)            # 不抛
