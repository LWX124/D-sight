import httpx
import pytest

from app.social.providers.redfox import RedFoxProvider


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
