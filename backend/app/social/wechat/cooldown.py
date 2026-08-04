"""微信 mp 接口熔断状态。

两类冷却，都存 Redis（复用 app.core.ratelimit 的连接）：

- **全局熔断**：命中 freq control(200013) 后，冷却期内不再向微信发任何 mp 请求。
  微信的风控窗口是按调用方计的，冷却期继续打只会不断给封禁续期。
- **按账号 refresh 冷却**：挡住手动刷新连点，避免和定时轮询叠加打满配额。

Redis 不可用时一律 fail-open（与 `app.core.ratelimit.check_rate` 约定一致）：
宁可放行，也不能因为缓存挂了就让功能整体不可用。
"""

import logging

from app.core.ratelimit import _redis

_log = logging.getLogger(__name__)

_GLOBAL_KEY = "wx:cooldown:mp"


def _refresh_key(account_id: str) -> str:
    return f"wx:cooldown:refresh:{account_id}"


async def remaining() -> int:
    """全局冷却剩余秒数；0 表示当前无冷却。"""
    try:
        ttl = await _redis().ttl(_GLOBAL_KEY)
    except Exception as e:  # noqa: BLE001 — redis 挂则放行
        _log.warning("wechat cooldown check failed, fail-open: %s", e)
        return 0
    return ttl if ttl > 0 else 0


async def trip(seconds: int) -> None:
    """触发全局冷却 `seconds` 秒。已在冷却中则续到较长的那个。"""
    try:
        r = _redis()
        current = await r.ttl(_GLOBAL_KEY)
        if current > seconds:
            return
        await r.set(_GLOBAL_KEY, "1", ex=seconds)
    except Exception as e:  # noqa: BLE001 — redis 挂了也不能让抓取链路崩
        _log.warning("wechat cooldown trip failed: %s", e)
        return
    _log.warning("wechat mp 命中风控，全局冷却 %d 秒", seconds)


async def clear() -> None:
    """手动解除全局冷却（运维/测试用）。"""
    try:
        await _redis().delete(_GLOBAL_KEY)
    except Exception as e:  # noqa: BLE001
        _log.warning("wechat cooldown clear failed: %s", e)


async def release_refresh(account_id: str) -> None:
    """释放某账号的 refresh 名额。用于失败路径（如凭证失效），避免用户修好后还被冷却挡住。"""
    try:
        await _redis().delete(_refresh_key(account_id))
    except Exception as e:  # noqa: BLE001
        _log.warning("wechat refresh cooldown release failed: %s", e)


async def try_acquire_refresh(account_id: str, seconds: int) -> int:
    """占用某账号的 refresh 名额。返回 0 表示允许，>0 表示还需等待的秒数。"""
    try:
        r = _redis()
        ok = await r.set(_refresh_key(account_id), "1", ex=seconds, nx=True)
        if ok:
            return 0
        ttl = await r.ttl(_refresh_key(account_id))
        return ttl if ttl > 0 else 0
    except Exception as e:  # noqa: BLE001 — redis 挂则放行
        _log.warning("wechat refresh cooldown check failed, fail-open: %s", e)
        return 0
