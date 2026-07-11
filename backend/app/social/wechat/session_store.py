from app.core.ratelimit import _redis

_TTL = 300  # 5 分钟


def _key(session_id: str) -> str:
    return f"wxlogin:{session_id}"


async def save(session_id: str, cookies: str) -> None:
    await _redis().set(_key(session_id), cookies, ex=_TTL)


async def load(session_id: str) -> str | None:
    return await _redis().get(_key(session_id))


async def delete(session_id: str) -> None:
    await _redis().delete(_key(session_id))
