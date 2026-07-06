import os

import httpx
import trafilatura
from langchain_core.tools import tool

BOCHA_ENDPOINT = "https://api.bochaai.com/v1/web-search"


@tool
def web_search(query: str, count: int = 8) -> str:
    """联网搜索，返回标题/链接/摘要。用于收集新闻、研报、财务数据线索、多空观点。"""
    resp = httpx.post(
        BOCHA_ENDPOINT,
        headers={"Authorization": f"Bearer {os.environ['BOCHA_API_KEY']}"},
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
    resp = httpx.get(
        url, timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
    )
    resp.raise_for_status()
    text = trafilatura.extract(resp.text) or ""
    return text[:8000] or "（未能提取正文）"
