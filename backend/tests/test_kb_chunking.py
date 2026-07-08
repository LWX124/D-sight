import pytest

from app.kb.chunking import chunk_text, parse_document


def test_parse_txt_utf8_and_gbk():
    assert parse_document("a.txt", "贵州茅台".encode("utf-8")) == "贵州茅台"
    assert parse_document("a.md", "贵州茅台".encode("gb18030")) == "贵州茅台"


def test_parse_rejects_unknown_ext():
    with pytest.raises(ValueError):
        parse_document("a.exe", b"x")


def test_chunk_overlap_and_skip_blank():
    text = "一" * 1000
    chunks = chunk_text(text, size=400, overlap=100)
    assert len(chunks) == 3  # 0-400, 300-700, 600-1000
    assert all(len(c) <= 400 for c in chunks)
    assert chunk_text("   \n  ") == []
