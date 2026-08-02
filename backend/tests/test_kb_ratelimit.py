import asyncio
import time

import pytest

from app.core import config
from app.kb.ratelimit import article_fetch_slot, reset_for_tests


@pytest.fixture
def fast_limiter(monkeypatch):
    monkeypatch.setenv("KB_BACKFILL_DELAY_SECONDS", "0.05")
    config.get_settings.cache_clear()
    reset_for_tests()
    yield
    config.get_settings.cache_clear()
    reset_for_tests()


@pytest.mark.asyncio
async def test_slot_serializes_concurrent_fetches(fast_limiter):
    """并发进入时必须串行，不能有两个同时持有 slot。"""
    active, peak = 0, 0

    async def worker():
        nonlocal active, peak
        async with article_fetch_slot():
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(*(worker() for _ in range(5)))
    assert peak == 1


@pytest.mark.asyncio
async def test_slot_enforces_minimum_interval(fast_limiter):
    started = []

    async def worker():
        async with article_fetch_slot():
            started.append(time.monotonic())

    await asyncio.gather(*(worker() for _ in range(3)))
    started.sort()
    gaps = [b - a for a, b in zip(started, started[1:], strict=False)]
    assert all(g >= 0.04 for g in gaps), gaps    # 0.05 间隔留一点抖动余量


@pytest.mark.asyncio
async def test_slot_releases_on_exception(fast_limiter):
    """抓取抛异常也必须释放，否则一次失败会永久卡死整条链路。"""
    with pytest.raises(RuntimeError):
        async with article_fetch_slot():
            raise RuntimeError("boom")
    async with article_fetch_slot():         # 还能再进
        pass
