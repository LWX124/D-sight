import pytest


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    async def ttl(self, key):
        return self.ttls.get(key, -2)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.ttls[key] = ex
        return True

    async def delete(self, key):
        self.values.pop(key, None)
        self.ttls.pop(key, None)


@pytest.mark.asyncio
async def test_global_and_refresh_cooldowns_are_independent(monkeypatch):
    from app.social.weibo import cooldown

    redis = FakeRedis()
    monkeypatch.setattr(cooldown, "_redis", lambda: redis)
    await cooldown.trip(120)
    assert await cooldown.remaining() == 120
    assert await cooldown.try_acquire_refresh("account-1", 30) == 0
    assert await cooldown.try_acquire_refresh("account-1", 30) == 30
    assert await cooldown.try_acquire_refresh("account-2", 30) == 0
    await cooldown.clear()
    assert await cooldown.remaining() == 0


@pytest.mark.asyncio
async def test_cooldown_fails_open_when_redis_is_unavailable(monkeypatch):
    from app.social.weibo import cooldown

    def unavailable():
        raise ConnectionError("redis down")

    monkeypatch.setattr(cooldown, "_redis", unavailable)
    assert await cooldown.remaining() == 0
    assert await cooldown.try_acquire_refresh("account-1", 30) == 0
    await cooldown.trip(30)
