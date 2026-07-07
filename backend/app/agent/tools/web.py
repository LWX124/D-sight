import os

import httpx
import trafilatura
from langchain_core.tools import tool

from app.agent.tools.safe import tool_guard

BOCHA_ENDPOINT = "https://api.bochaai.com/v1/web-search"


@tool
@tool_guard
def web_search(query: str, count: int = 8) -> str:
    """联网搜索，返回标题/链接/摘要。用于收集新闻、研报、财务数据线索、多空观点。"""
    api_key = os.environ.get("BOCHA_API_KEY")
    if not api_key:
        return "错误：搜索服务未配置（缺少 BOCHA_API_KEY），请改用其他工具（如 stock_quote/stock_financials/fetch_page）或告知用户此题需要联网搜索。"
    resp = httpx.post(
        BOCHA_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"query": query, "count": count, "summary": True},
        timeout=30,
    )
    resp.raise_for_status()
    items = resp.json().get("data", {}).get("webPages", {}).get("value", [])
    if not items:
        return "（无搜索结果）"
    return "\n".join(
        f"- {it.get('name')}\n  {it.get('url')}\n  {it.get('summary') or it.get('snippet', '')}"
        for it in items
    )


@tool
def fetch_page(url: str) -> str:
    """抓取网页并提取正文文本（截断到 8000 字符）。用于阅读搜索结果的原文。"""
    return _fetch_page_impl(url)


@tool_guard
def _fetch_page_impl(url: str) -> str:
    resp = httpx.get(
        url, timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
    )
    resp.raise_for_status()
    html = resp.content.decode(_detect_encoding(resp), errors="replace")
    text = trafilatura.extract(html) or ""
    return text[:8000] or "（未能提取正文）"


def _detect_encoding(resp: httpx.Response) -> str:
    """头部有 charset 用头部；否则从 meta/内容探测（中文站大量 GBK）。

    末端兜底不能盲信 utf-8：许多中文站既无 HTTP charset 也无 meta 声明，直接
    以 GBK 落字节。故先按 utf-8 严格试解，失败即判定为 gb18030（GBK 高位字节
    不构成合法 utf-8 序列，判别可靠；短中文样本用 charset_normalizer 会误判成
    cp949，反不如此法稳）。
    """
    ctype = resp.headers.get("content-type", "")
    if "charset=" in ctype:
        return ctype.split("charset=")[-1].split(";")[0].strip()
    head = resp.content[:2048].lower()
    if b"gbk" in head or b"gb2312" in head or b"gb18030" in head:
        return "gb18030"
    try:
        resp.content.decode("utf-8")
    except UnicodeDecodeError:
        return "gb18030"
    return "utf-8"
