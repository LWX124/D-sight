import logging

import redis.asyncio as aioredis

from app.core.config import get_settings

_log = logging.getLogger(__name__)
_client: aioredis.Redis | None = None


def _redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


async def check_rate(user_id: str) -> bool:
    """固定窗口：每分钟每用户至多 rate_limit_per_min 次。redis 挂则放行（fail-open）。"""
    s = get_settings()
    try:
        from datetime import UTC, datetime

        window = datetime.now(UTC).strftime("%Y%m%d%H%M")
        key = f"rl:{user_id}:{window}"
        r = _redis()
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, 70)
        return n <= s.rate_limit_per_min
    except Exception as e:  # noqa: BLE001
        _log.warning("rate limit check failed, fail-open: %s", e)
        return True
