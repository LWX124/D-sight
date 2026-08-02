"""公众号正文抓取的进程内限流器。

后台回填与用户点开文章的懒抓共用同一个 slot——否则回填会把前台阅读挤到超时。
单进程语义（信号量 + 单调时钟），多副本部署时每个进程各限一份；当前部署形态为
单进程，够用。
"""
import asyncio
import contextlib
import time

from app.core.config import get_settings

_lock: asyncio.Lock | None = None
_last_at: float = 0.0


def _get_lock() -> asyncio.Lock:
    # 懒建：模块导入时可能还没有 event loop
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def reset_for_tests() -> None:
    global _lock, _last_at
    _lock = None
    _last_at = 0.0


@contextlib.asynccontextmanager
async def article_fetch_slot():
    """串行化正文抓取，并保证两次抓取间隔不小于 kb_backfill_delay_seconds。"""
    global _last_at
    delay = get_settings().kb_backfill_delay_seconds
    async with _get_lock():
        wait = _last_at + delay - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            yield
        finally:
            # 以「抓取结束」为计时起点，异常路径同样计时——失败往往正是被限流，
            # 不计时会让重试立刻再撞一次。
            _last_at = time.monotonic()
