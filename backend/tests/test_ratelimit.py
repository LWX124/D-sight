from types import SimpleNamespace

import pytest

from app.core import ratelimit


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key, ttl):
        return True


@pytest.mark.asyncio
async def test_allows_under_limit_then_blocks(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(ratelimit, "_redis", lambda: fake)
    monkeypatch.setattr(
        ratelimit, "get_settings", lambda: SimpleNamespace(rate_limit_per_min=3)
    )
    # 前 3 次放行，第 4 次拦
    results = [await ratelimit.check_rate("u1") for _ in range(4)]
    assert results[:3] == [True, True, True]
    assert results[3] is False


@pytest.mark.asyncio
async def test_fail_open_on_redis_error(monkeypatch):
    def boom():
        raise RuntimeError("down")

    monkeypatch.setattr(ratelimit, "_redis", boom)
    assert await ratelimit.check_rate("u1") is True
