import datetime as dt
import json
from dataclasses import dataclass

from selectolax.parser import HTMLParser

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
            out.append(RawArticle(
                external_id=str(a["aid"]),
                title=a.get("title", ""),
                digest=_nz(a.get("digest")),
                cover_url=_nz(a.get("cover")),
                url=a.get("link", ""),
                published_at=dt.datetime.fromtimestamp(int(a.get("create_time", 0)), tz=dt.UTC),
            ))
    return out


def html_to_text(html: str) -> str:
    """抠 #js_content 正文区，剥成纯文本（段落间换行）。找不到则退化为全文文本。"""
    tree = HTMLParser(html)
    node = tree.css_first("#js_content")
    target = node if node is not None else tree.body
    if target is None:
        return ""
    for bad in target.css("script, style"):
        bad.decompose()
    text = target.text(separator="\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)
