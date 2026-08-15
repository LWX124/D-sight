import json
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.social.wechat.client import ActiveCred, appmsg_publish, search_biz


def _cred():
    return ActiveCred(id=uuid.uuid4(), token="tok", cookies="slave_sid=abc")


@pytest.mark.asyncio
async def test_search_biz_maps_fields_and_auth():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["cookie"] = request.headers.get("cookie")
        body = {"base_resp": {"ret": 0}, "list": [
            {"fakeid": "F1", "nickname": "号A", "round_head_img": "http://a", "signature": "sig"},
        ]}
        return httpx.Response(200, json=body)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with http:
        rows = await search_biz(http, _cred(), "关键词")

    assert rows == [{"fakeid": "F1", "nickname": "号A", "avatar": "http://a", "signature": "sig"}]
    assert "token=tok" in captured["url"]
    assert "query=" in captured["url"]
    assert captured["cookie"] == "slave_sid=abc"


@pytest.mark.asyncio
async def test_appmsg_publish_parses_articles():
    appmsgex = [{"aid": "9_1", "title": "T", "digest": "d", "cover": "c",
                 "link": "https://mp/s/x", "create_time": 1751000000}]
    publish_info = json.dumps({"appmsgex": appmsgex})
    publish_page = json.dumps({"publish_list": [{"publish_info": publish_info}], "total_count": 1})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"base_resp": {"ret": 0}, "publish_page": publish_page})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with http:
        arts = await appmsg_publish(http, _cred(), "F1")

    assert len(arts) == 1
    assert arts[0].external_id == "9_1"


@pytest.mark.asyncio
async def test_session_expired_propagates():
    from app.social.wechat.errors import SessionExpiredError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"base_resp": {"ret": 200003, "err_msg": "x"}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with http:
        with pytest.raises(SessionExpiredError):
            await appmsg_publish(http, _cred(), "F1")


@pytest.mark.asyncio
async def test_non_json_response_raises_transient():
    from app.social.wechat.errors import TransientMpError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>captcha</html>")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with http:
        with pytest.raises(TransientMpError):
            await appmsg_publish(http, _cred(), "F1")


@pytest.mark.asyncio
async def test_http_failure_does_not_expose_token_or_cookie():
    from app.social.wechat.errors import TransientMpError

    secret_cred = ActiveCred(
        id=uuid.uuid4(),
        token="secret-query-token",
        cookies="slave_sid=secret-cookie",
    )
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    )
    async with http:
        with pytest.raises(TransientMpError) as exc_info:
            await appmsg_publish(http, secret_cred, "private-fakeid")

    message = str(exc_info.value)
    assert "secret-query-token" not in message
    assert "secret-cookie" not in message
    assert "private-fakeid" not in message


@pytest.mark.asyncio
async def test_fallback_budget_reserves_each_attempt_including_http_failure(
    monkeypatch,
):
    from app.core import config
    from app.social import budget
    from app.social.wechat.errors import TransientMpError

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(social_wechat_fallback_enabled=True),
    )
    reservations = 0

    async def reserve() -> int:
        nonlocal reservations
        reservations += 1
        return 49 - reservations

    monkeypatch.setattr(budget, "reserve_wechat_request", reserve)
    responses = iter(
        [
            httpx.Response(200, json={"base_resp": {"ret": 0}, "list": []}),
            httpx.Response(
                200,
                json={
                    "base_resp": {"ret": 0},
                    "publish_page": json.dumps(
                        {"publish_list": [], "total_count": 0}
                    ),
                },
            ),
            httpx.Response(503),
        ]
    )
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return next(responses)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http:
        await search_biz(http, _cred(), "关键词")
        await appmsg_publish(http, _cred(), "F1")
        with pytest.raises(TransientMpError):
            await appmsg_publish(http, _cred(), "F1")

    assert reservations == 3
    assert requests == 3
