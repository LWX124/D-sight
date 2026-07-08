import asyncio
import io
import uuid

import pytest

from app.kb.chunking import chunk_text, parse_document
from app.kb.retrieval import search_chunks
from tests.conftest import _auth


@pytest.mark.asyncio
async def test_upload_then_retrieve_with_source(client, db_session, registered_user):
    """端到端闭环（T4/T5/T6）：真实端点上传 txt → 轮询至 ready → 检索命中且带出处 filename。"""
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "研报"}, headers=h)).json()["id"]
    files = {
        "file": ("maotai.txt", io.BytesIO("贵州茅台2025年净利润大幅增长。".encode("utf-8")), "text/plain"),
    }
    up = await client.post(f"/api/kb/{kb_id}/documents", files=files, headers=h)
    assert up.status_code == 200

    for _ in range(50):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if docs and docs[0]["status"] in ("ready", "failed"):
            break
        await asyncio.sleep(0.1)
    assert docs[0]["status"] == "ready"

    hits = await search_chunks(db_session, [uuid.UUID(kb_id)], "茅台 净利润")
    assert hits and hits[0]["filename"] == "maotai.txt"


# --- T3 review-gap 补测 1：PDF 解析分支覆盖 -------------------------------------
# reportlab 未安装（`uv pip show reportlab` 无结果），故走无新增依赖路径：
# 用已是依赖的 pypdf 生成一页空白 PDF，断言 parse_document 走 pdf 分支、
# 返回 str 且不抛异常（空白页无可抽取文本，结果为空/纯空白）。
def test_parse_pdf_branch_no_crash_on_blank_page():
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    text = parse_document("x.pdf", pdf_bytes)
    assert isinstance(text, str)
    assert text.strip() == ""  # 空白页无可抽取文本，但 pdf 分支已执行且未崩溃


# --- T3 review-gap 补测 2：切片重叠 + 全文覆盖 -----------------------------------
# 用 1000 个互异字符（而非同字符），使"重叠相等"与"覆盖唯一"均为实证断言。
def test_chunk_overlap_and_full_coverage():
    text = "".join(chr(0x4E00 + i) for i in range(1000))  # 1000 个互异 CJK 字符
    chunks = chunk_text(text, size=400, overlap=100)
    assert len(chunks) == 3  # [0:400] [300:700] [600:1000]
    # 相邻切片确有 100 字重叠
    assert chunks[0][-100:] == chunks[1][:100]
    assert chunks[1][-100:] == chunks[2][:100]
    # 去重拼接后无缝覆盖全部 1000 个字符
    reconstructed = chunks[0] + chunks[1][100:] + chunks[2][100:]
    assert reconstructed == text
    assert len(set(text)) == 1000  # 确为互异字符，覆盖断言非平凡
