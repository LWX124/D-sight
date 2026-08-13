import datetime as dt
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser as StdlibHTMLParser

from selectolax.parser import HTMLParser as SelectolaxHTMLParser

from app.social.wechat.errors import check_base_resp


@dataclass
class RawArticle:
    external_id: str
    title: str
    digest: str | None
    cover_url: str | None
    url: str
    published_at: dt.datetime


def _nz(s: str | None) -> str | None:
    """空串归一为 None。"""
    return s or None


_HTML_TAG_RE = re.compile(r"</?([A-Za-z][A-Za-z0-9:-]*)\b[^>]*>")
# Real RedFox payloads use runs of 4, 5, 7, or 14 spaces as paragraph marks.
# Two-space runs also occur inside sentences and links, so they stay inline.
_PLAINTEXT_PARAGRAPH_GAP_RE = re.compile(r"[^\S\r\n]{4,}")
_HORIZONTAL_WHITESPACE_RE = re.compile(r"[^\S\r\n]+")
_HTML_DATA_WHITESPACE_RE = re.compile(r"\s+")
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
_KNOWN_HTML_TAGS = _BLOCK_TAGS | {
    "a",
    "abbr",
    "b",
    "bdi",
    "bdo",
    "body",
    "br",
    "cite",
    "code",
    "del",
    "em",
    "font",
    "head",
    "html",
    "i",
    "img",
    "ins",
    "label",
    "mark",
    "q",
    "s",
    "script",
    "small",
    "span",
    "strike",
    "strong",
    "style",
    "sub",
    "sup",
    "time",
    "u",
    "var",
    "wbr",
}


class _BlockAwareTextParser(StdlibHTMLParser):
    """Extract text while treating HTML blocks, rather than every node, as paragraphs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0
        self._preformatted_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self._ignored_depth += 1
        elif self._ignored_depth == 0:
            if tag == "br":
                self.parts.append("\n")
            elif tag in _BLOCK_TAGS:
                self.parts.append("\n\n")
            if tag == "pre":
                self._preformatted_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if self._ignored_depth == 0 and tag not in {"script", "style"}:
            if tag == "br":
                self.parts.append("\n")
            elif tag in _BLOCK_TAGS:
                self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif self._ignored_depth == 0:
            if tag == "pre":
                self._preformatted_depth = max(0, self._preformatted_depth - 1)
            if tag in _BLOCK_TAGS:
                self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(
                data if self._preformatted_depth else _HTML_DATA_WHITESPACE_RE.sub(" ", data)
            )


def _normalize_plaintext(content: str) -> str:
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = _PLAINTEXT_PARAGRAPH_GAP_RE.sub("\n\n", content)
    lines = [_HORIZONTAL_WHITESPACE_RE.sub(" ", line).strip() for line in content.split("\n")]
    content = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", content).strip()


def _normalize_html(content: str) -> str:
    parser = _BlockAwareTextParser()
    parser.feed(content)
    parser.close()
    text = "".join(parser.parts).replace("\r\n", "\n").replace("\r", "\n")
    text = _HORIZONTAL_WHITESPACE_RE.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{2,}", "\n\n", text).strip()


def _looks_like_html(content: str) -> bool:
    return any(
        match.group(1).lower() in _KNOWN_HTML_TAGS for match in _HTML_TAG_RE.finditer(content)
    )


def parse_appmsgpublish(data: dict) -> list[RawArticle]:
    check_base_resp(data)
    raw = data.get("publish_page")
    if not raw:
        return []
    page = json.loads(raw)
    out: list[RawArticle] = []
    for item in page.get("publish_list", []):
        info_raw = item.get("publish_info")
        if not info_raw:
            continue
        info = json.loads(info_raw)
        for a in info.get("appmsgex", []):
            out.append(
                RawArticle(
                    external_id=str(a["aid"]),
                    title=a.get("title", ""),
                    digest=_nz(a.get("digest")),
                    cover_url=_nz(a.get("cover")),
                    url=a.get("link", ""),
                    published_at=dt.datetime.fromtimestamp(int(a.get("create_time", 0)), tz=dt.UTC),
                )
            )
    return out


def html_to_text(html: str) -> str:
    """将公众号 HTML 或 RedFox 纯文本正文归一为带语义段落的纯文本。"""
    if not html or not _looks_like_html(html):
        return _normalize_plaintext(html)

    tree = SelectolaxHTMLParser(html)
    node = tree.css_first("#js_content")
    target = node if node is not None else tree.body
    if target is None:
        return ""
    return _normalize_html(target.html)
