import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from app.core.config import get_settings
from app.social.weibo.errors import (
    InvalidWeiboPayloadError,
    WeiboRateLimitedError,
    WeiboSessionExpiredError,
    WeiboTransientError,
)
from app.social.weibo.parser import (
    RawWeiboPost,
    WeiboProfile,
    parse_login,
    parse_posts,
    parse_profile,
    parse_status,
)

_BASE_URL = "https://m.weibo.cn"
_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://m.weibo.cn/",
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
    ),
}


class WeiboClient:
    def __init__(self, http: httpx.AsyncClient, cookies: str):
        self.http = http
        self.cookies = cookies

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = await self.http.get(
                path, params=params, headers={**_HEADERS, "Cookie": self.cookies}
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise WeiboTransientError("微博请求超时或网络不可用") from exc
        if response.status_code in {403, 432}:
            raise WeiboRateLimitedError(f"微博接口返回 HTTP {response.status_code}")
        if response.status_code >= 500:
            raise WeiboTransientError(f"微博接口返回 HTTP {response.status_code}")
        if response.status_code >= 400:
            raise WeiboTransientError(f"微博接口返回 HTTP {response.status_code}")
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise InvalidWeiboPayloadError("微博接口返回了非 JSON 内容") from exc
        if isinstance(payload, dict) and payload.get("ok") == -100:
            raise WeiboSessionExpiredError("微博登录态已失效")
        if isinstance(payload, dict) and payload.get("ok") == 0:
            raise WeiboTransientError(str(payload.get("msg") or "微博接口返回失败"))
        return payload

    async def verify(self) -> tuple[str | None, str | None, str | None]:
        return parse_login(await self._get("/api/config"))

    async def get_profile(self, uid: str) -> WeiboProfile:
        payload = await self._get("/api/container/getIndex", {"type": "uid", "value": uid})
        return parse_profile(payload, uid)

    async def get_posts(self, uid: str, container_id: str, page: int) -> list[RawWeiboPost]:
        payload = await self._get(
            "/api/container/getIndex",
            {"type": "uid", "value": uid, "containerid": container_id, "page": page},
        )
        return parse_posts(payload)

    async def get_status(self, bid: str) -> RawWeiboPost:
        return parse_status(await self._get("/statuses/show", {"id": bid}))


@asynccontextmanager
async def new_weibo_client(cookies: str) -> AsyncIterator[WeiboClient]:
    timeout = get_settings().weibo_request_timeout_seconds
    async with httpx.AsyncClient(
        base_url=_BASE_URL, timeout=timeout, follow_redirects=False
    ) as http:
        yield WeiboClient(http, cookies)
