import logging

from app.core.ratelimit import _redis

_log = logging.getLogger(__name__)
_GLOBAL_KEY = "weibo:cooldown:global"


def _refresh_key(account_id: str) -> str:
    return f"weibo:cooldown:refresh:{account_id}"


async def remaining() -> int:
    try:
        ttl = await _redis().ttl(_GLOBAL_KEY)
        return ttl if ttl > 0 else 0
    except Exception as exc:  # noqa: BLE001
        _log.warning("weibo cooldown check failed, fail-open: %s", exc)
        return 0


async def trip(seconds: int) -> None:
    try:
        redis = _redis()
        current = await redis.ttl(_GLOBAL_KEY)
        if current <= seconds:
            await redis.set(_GLOBAL_KEY, "1", ex=seconds)
    except Exception as exc:  # noqa: BLE001
        _log.warning("weibo cooldown trip failed: %s", exc)


async def clear() -> None:
    try:
        await _redis().delete(_GLOBAL_KEY)
    except Exception as exc:  # noqa: BLE001
        _log.warning("weibo cooldown clear failed: %s", exc)


async def try_acquire_refresh(account_id: str, seconds: int) -> int:
    try:
        redis = _redis()
        if await redis.set(_refresh_key(account_id), "1", ex=seconds, nx=True):
            return 0
        ttl = await redis.ttl(_refresh_key(account_id))
        return ttl if ttl > 0 else 0
    except Exception as exc:  # noqa: BLE001
        _log.warning("weibo refresh cooldown check failed, fail-open: %s", exc)
        return 0


async def release_refresh(account_id: str) -> None:
    try:
        await _redis().delete(_refresh_key(account_id))
    except Exception as exc:  # noqa: BLE001
        _log.warning("weibo refresh cooldown release failed: %s", exc)
