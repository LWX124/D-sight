import httpx
import pytest

from app.social.weibo.client import WeiboClient
from app.social.weibo.credentials import validate_cookies
from app.social.weibo.errors import (
    InvalidWeiboPayloadError,
    WeiboRateLimitedError,
    WeiboSessionExpiredError,
    WeiboTransientError,
)


@pytest.mark.asyncio
async def test_client_sends_cookie_and_verifies_login():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["cookie"] == "SUB=test-only"
        return httpx.Response(200, json={"data": {"login": True, "userInfo": {"id": 1}}})

    async with httpx.AsyncClient(
        base_url="https://m.weibo.cn", transport=httpx.MockTransport(handler)
    ) as http:
        result = await WeiboClient(http, "SUB=test-only").verify()
    assert result[0] == "1"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 432])
async def test_client_maps_rate_limit(status):
    async with httpx.AsyncClient(
        base_url="https://m.weibo.cn",
        transport=httpx.MockTransport(lambda request: httpx.Response(status)),
    ) as http:
        with pytest.raises(WeiboRateLimitedError):
            await WeiboClient(http, "test=1").verify()


@pytest.mark.asyncio
async def test_client_maps_expired_5xx_and_non_json():
    responses = iter(
        [
            httpx.Response(200, json={"ok": -100}),
            httpx.Response(503),
            httpx.Response(200, text="<html>login</html>"),
        ]
    )
    async with httpx.AsyncClient(
        base_url="https://m.weibo.cn",
        transport=httpx.MockTransport(lambda request: next(responses)),
    ) as http:
        client = WeiboClient(http, "test=1")
        with pytest.raises(WeiboSessionExpiredError):
            await client.verify()
        with pytest.raises(WeiboTransientError):
            await client.verify()
        with pytest.raises(InvalidWeiboPayloadError):
            await client.verify()


def test_cookie_validation_blocks_header_injection_and_oversize():
    assert validate_cookies("  SUB=test-only  ") == "SUB=test-only"
    with pytest.raises(ValueError, match="换行"):
        validate_cookies("SUB=x\r\nX-Injected: yes")
    with pytest.raises(ValueError, match="16 KiB"):
        validate_cookies("x" * (16 * 1024 + 1))
