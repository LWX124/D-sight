import httpx
import pytest

from app.social.providers.base import ItemDTO, ProviderCoverageGap, PublisherDTO
from app.social.providers.redfox import RedFoxProvider
from app.social.providers.wechat_mp import WechatMpProvider


@pytest.mark.asyncio
async def test_redfox_xiaohongshu_search_items_uses_verified_endpoint_and_shared_client():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "code": 2000,
                "data": {
                    "list": [
                        {
                            "workId": "work-1",
                            "workTitle": "金融笔记",
                            "workDesc": "正文",
                            "workPublishTime": "2026-08-11 08:00:00",
                            "workLikedCount": 12,
                        }
                    ]
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = RedFoxProvider("test-key", client=client, base_url="https://redfox.test")
    items = await provider.search_items("xiaohongshu", "金融", limit=10)
    publishers = provider.capabilities("xiaohongshu")

    assert requests[0].url.path == "/story/api/xhsUser/searchArticle"
    assert requests[0].headers["REDFOX_API_KEY"] == "test-key"
    assert items[0].external_id == "work-1"
    assert items[0].body_text == "正文"
    assert items[0].published_at.tzinfo is not None
    assert publishers["account_item_list"] is False
    assert publishers["item_search"] is True
    raw_records = provider.drain_raw_records()
    assert raw_records == [
        {
            "platform": "xiaohongshu",
            "operation": "/story/api/xhsUser/searchArticle",
            "payload": {
                "code": 2000,
                "data": {
                    "list": [
                        {
                            "workId": "work-1",
                            "workTitle": "金融笔记",
                            "workDesc": "正文",
                            "workPublishTime": "2026-08-11 08:00:00",
                            "workLikedCount": 12,
                        }
                    ]
                },
            },
        }
    ]
    assert provider.drain_raw_records() == []
    await client.aclose()


@pytest.mark.asyncio
async def test_redfox_xiaohongshu_publisher_items_is_not_silent():
    from app.social.providers.base import PublisherDTO

    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    provider = RedFoxProvider("test-key", client=client)
    with pytest.raises(NotImplementedError, match="no Xiaohongshu account item-list"):
        await provider.fetch_publisher_items(
            PublisherDTO(platform="xiaohongshu", external_id="u1", name="user")
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_redfox_wechat_detail_uses_verified_url_endpoint_and_maps_content():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "code": 2000,
                "data": {
                    "content": "RedFox 返回的公众号正文       第二段\n第二段补充",
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = RedFoxProvider("test-key", client=client, base_url="https://redfox.test")
    source = ItemDTO(
        platform="wechat",
        external_id="article-1",
        content_type="article",
        title="文章标题",
        url="https://mp.weixin.qq.com/s/verified-article",
    )

    detail = await provider.fetch_item_detail(source)

    assert len(requests) == 1
    assert requests[0].url.path == "/story/api/gzhData/queryArticleDetail"
    assert requests[0].headers["REDFOX_API_KEY"] == "test-key"
    assert requests[0].method == "POST"
    assert requests[0].read() == (b'{"url":"https://mp.weixin.qq.com/s/verified-article"}')
    assert detail.platform == source.platform
    assert detail.external_id == source.external_id
    assert detail.content_type == source.content_type
    assert detail.url == source.url
    assert detail.body_text == "RedFox 返回的公众号正文\n\n第二段\n第二段补充"
    assert provider.capabilities("wechat")["detail"] is True
    assert WechatMpProvider().capabilities("wechat")["detail"] is False
    raw_records = provider.drain_raw_records()
    assert raw_records[0]["operation"] == "/story/api/gzhData/queryArticleDetail"
    await client.aclose()


@pytest.mark.asyncio
async def test_redfox_wechat_detail_rejects_untrusted_url_before_http_request():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = RedFoxProvider("test-key", client=client)

    with pytest.raises(ValueError, match="allowed article URL"):
        await provider.fetch_item_detail(
            ItemDTO(
                platform="wechat",
                external_id="article-1",
                content_type="article",
                url="https://mp.weixin.qq.com.evil.test/s/article-1",
            )
        )

    assert requests == []
    await client.aclose()


@pytest.mark.asyncio
async def test_redfox_explicit_wechat_noncoverage_is_typed():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": 4004, "msg": "优质库暂未收录该公众号", "data": None},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = RedFoxProvider("test-key", client=client)
    with pytest.raises(ProviderCoverageGap) as exc_info:
        await provider.fetch_publisher_items(
            PublisherDTO(
                platform="wechat",
                external_id="redfox-account",
                name="未收录账号",
                provider="redfox",
            )
        )
    assert exc_info.value.code == "provider_coverage_gap"
    await client.aclose()


@pytest.mark.asyncio
async def test_redfox_transient_wechat_failure_is_not_a_coverage_gap():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    )
    provider = RedFoxProvider("test-key", client=client)
    with pytest.raises(httpx.HTTPStatusError):
        await provider.fetch_publisher_items(
            PublisherDTO(platform="wechat", external_id="a", name="A")
        )
    await client.aclose()
