from datetime import datetime, timedelta, timezone

import pytest

from app.aihot.ranking import compute_freshness_score, rank_items


NOW = datetime(2026, 8, 11, 8, tzinfo=timezone.utc)


def _item(item_id, platform, age_hours, *, like=0, provider_rank=None):
    return {
        "item_id": item_id,
        "platform": platform,
        "category": "market",
        "published_at": NOW - timedelta(hours=age_hours),
        "provider_rank": provider_rank,
        "metrics": {"like": like},
    }


def test_freshness_has_24_hour_half_life():
    assert compute_freshness_score(NOW, NOW) == pytest.approx(100)
    assert compute_freshness_score(NOW - timedelta(hours=24), NOW) == pytest.approx(50)


def test_windows_are_cumulative_and_do_not_include_future_items():
    items = [
        _item("recent", "wechat", 2, like=10),
        _item("two-days", "wechat", 48, like=20),
        _item("five-days", "wechat", 120, like=30),
        _item("future", "wechat", -1, like=1000),
    ]
    assert {row["item_id"] for row in rank_items(items, window="24h", now=NOW)} == {
        "recent"
    }
    assert {row["item_id"] for row in rank_items(items, window="3d", now=NOW)} == {
        "recent",
        "two-days",
    }
    assert {row["item_id"] for row in rank_items(items, window="7d", now=NOW)} == {
        "recent",
        "two-days",
        "five-days",
    }


def test_absolute_metrics_never_cross_platform_boundary():
    rows = rank_items(
        [
            _item("wx-low", "wechat", 1, like=10),
            _item("wx-high", "wechat", 1, like=100),
            _item("bili-low", "bilibili", 1, like=10_000),
            _item("bili-high", "bilibili", 1, like=100_000),
        ],
        window="24h",
        now=NOW,
    )
    scores = {row["item_id"]: row["platform_score"] for row in rows}
    assert scores == {
        "wx-low": 0,
        "wx-high": 100,
        "bili-low": 0,
        "bili-high": 100,
    }


def test_saved_previous_rank_drives_trend_and_first_seen_is_neutral():
    rows = rank_items(
        [_item("a", "wechat", 1, like=100), _item("b", "wechat", 1, like=10)],
        window="24h",
        previous_ranks={"a": 2, "b": 1},
        now=NOW,
    )
    by_id = {row["item_id"]: row for row in rows}
    assert by_id["a"]["momentum_score"] > 50
    assert by_id["a"]["rank_delta"] == by_id["a"]["previous_rank"] - by_id["a"]["rank"]

    first = rank_items([_item("new", "wechat", 1, like=1)], window="24h", now=NOW)[0]
    assert first["momentum_score"] == 50
    assert first["previous_rank"] is None
    assert first["rank_delta"] is None
