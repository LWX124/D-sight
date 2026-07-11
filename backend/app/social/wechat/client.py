import json
import uuid
from dataclasses import dataclass

import httpx

from app.social.wechat.parser import RawArticle, parse_appmsgpublish

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_BASE_HEADERS = {
    "Referer": "https://mp.weixin.qq.com/",
    "Origin": "https://mp.weixin.qq.com",
    "User-Agent": _UA,
    "Accept-Encoding": "identity",
}


@dataclass
class ActiveCred:
    id: uuid.UUID
    token: str
    cookies: str  # 已解密的 cookie 串


def new_mp_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=_BASE_HEADERS, timeout=30, follow_redirects=True)


async def _mp_get_json(http: httpx.AsyncClient, endpoint: str, params: dict, cred: ActiveCred) -> dict:
    from app.social.wechat.errors import TransientMpError, check_base_resp

    p = {**params, "token": cred.token, "lang": "zh_CN", "f": "json", "ajax": "1"}
    r = await http.get(endpoint, params=p, headers={"Cookie": cred.cookies})
    r.raise_for_status()
    try:
        data = r.json()
    except json.JSONDecodeError as e:
        raise TransientMpError(f"微信返回非 JSON（可能被限流/验证页）: {e}") from e
    return check_base_resp(data)


async def search_biz(
    http: httpx.AsyncClient, cred: ActiveCred, keyword: str, begin: int = 0, size: int = 5
) -> list[dict]:
    data = await _mp_get_json(
        http, "https://mp.weixin.qq.com/cgi-bin/searchbiz",
        {"action": "search_biz", "begin": begin, "count": size, "query": keyword}, cred,
    )
    return [
        {
            "fakeid": it.get("fakeid"),
            "nickname": it.get("nickname"),
            "avatar": it.get("round_head_img"),
            "signature": it.get("signature"),
        }
        for it in data.get("list", [])
    ]


async def appmsg_publish(
    http: httpx.AsyncClient, cred: ActiveCred, fakeid: str, begin: int = 0, count: int = 20
) -> list[RawArticle]:
    data = await _mp_get_json(
        http, "https://mp.weixin.qq.com/cgi-bin/appmsgpublish",
        {
            "sub": "list", "search_field": "null", "begin": begin, "count": count,
            "query": "", "fakeid": fakeid, "type": "101_1", "free_publish_type": 1,
            "sub_action": "list_ex",
        },
        cred,
    )
    return parse_appmsgpublish(data)


async def fetch_article_text(http: httpx.AsyncClient, url: str) -> str:
    from app.social.wechat.parser import html_to_text

    r = await http.get(url)
    r.raise_for_status()
    return html_to_text(r.text)
