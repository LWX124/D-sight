import io


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gb18030", errors="replace")


def parse_document(filename: str, raw: bytes) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("txt", "md"):
        return _decode(raw)
    if ext == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    raise ValueError(f"不支持的文件类型：.{ext}（仅 txt/md/pdf）")


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks, start, n = [], 0, len(text)
    step = max(1, size - overlap)
    while start < n:
        piece = text[start:start + size].strip()
        if piece:
            chunks.append(piece)
        if start + size >= n:
            break
        start += step
    return chunks
