import datetime as dt

import pytest

from app.social.weibo.errors import InvalidWeiboPayloadError, WeiboSessionExpiredError
from app.social.weibo.parser import parse_login, parse_posts, parse_profile, parse_status


def test_parse_profile_and_container():
    profile = parse_profile(
        {
            "data": {
                "userInfo": {
                    "id": 123456,
                    "screen_name": "测试账号",
                    "profile_image_url": "https://img/avatar.jpg",
                    "description": "简介",
                },
                "tabsInfo": {"tabs": [{"tab_type": "weibo", "containerid": "107603123456"}]},
            }
        },
        "123456",
    )
    assert profile.uid == "123456"
    assert profile.container_id == "107603123456"


def test_parse_posts_filters_non_mblog_and_marks_repost():
    payload = {
        "data": {
            "cards": [
                {"card_type": 11},
                {
                    "mblog": {
                        "id": "1",
                        "bid": "B1",
                        "text": "原创<br>正文",
                        "created_at": "Wed Aug 06 10:00:00 +0800 2026",
                        "isTop": 1,
                        "pics": [{"large": {"url": "https://img/1.jpg"}}],
                    }
                },
                {
                    "mblog": {
                        "id": "2",
                        "bid": "B2",
                        "text": "转发",
                        "created_at": "Wed Aug 06 10:00:00 +0800 2026",
                        "retweeted_status": {"id": "x"},
                    }
                },
            ]
        }
    }
    rows = parse_posts(payload)
    assert len(rows) == 2
    assert rows[0].content == "原创\n正文"
    assert rows[0].published_at == dt.datetime(2026, 8, 6, 2, tzinfo=dt.UTC)
    assert rows[0].media == [{"type": "image", "url": "https://img/1.jpg"}]
    assert rows[0].is_pinned is True
    assert rows[1].is_repost is True


def test_parse_long_status_and_video():
    row = parse_status(
        {
            "data": {
                "id": "3",
                "bid": "B3",
                "text_raw": "完整长正文",
                "created_at": "2026-08-06T02:00:00Z",
                "page_info": {
                    "type": "video",
                    "urls": {"mp4_hd_mp4": "https://video/3.mp4"},
                    "page_pic": {"url": "https://img/poster.jpg"},
                },
            }
        }
    )
    assert row.content == "完整长正文"
    assert row.media[0]["type"] == "video"
    assert row.media[0]["poster_url"] == "https://img/poster.jpg"


def test_invalid_payload_and_logged_out_are_rejected():
    with pytest.raises(InvalidWeiboPayloadError):
        parse_posts({"data": {}})
    with pytest.raises(WeiboSessionExpiredError):
        parse_login({"data": {"login": False}})
