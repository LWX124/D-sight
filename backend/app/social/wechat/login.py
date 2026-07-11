import datetime as dt
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.social import crypto
from app.social.models import WechatCredential
from app.social.wechat import session_store
from app.social.wechat.client import new_mp_client

_QR = "https://mp.weixin.qq.com/cgi-bin/scanloginqrcode"
_BIZLOGIN = "https://mp.weixin.qq.com/cgi-bin/bizlogin"
_INFO = "https://mp.weixin.qq.com/cgi-bin/info"


async def start_qrcode() -> tuple[str, bytes]:
    """取二维码 + 建 login session。返回 (session_id, png 字节)。"""
    session_id = uuid.uuid4().hex
    async with new_mp_client() as http:
        r = await http.get(_QR, params={"action": "getqrcode", "random": "1"})
        r.raise_for_status()
        set_cookie = r.headers.get("set-cookie", "")
        uuid_cookie = ""
        for part in set_cookie.split(","):
            if "uuid=" in part:
                uuid_cookie = part.split(";")[0].strip()
                break
        await session_store.save(session_id, uuid_cookie)
        return session_id, r.content


async def poll_status(db: AsyncSession, session_id: str, user_id: uuid.UUID) -> dict:
    """轮询扫码态；确认(status=1)则 bizlogin 换 token、落库凭证。"""
    cookies = await session_store.load(session_id)
    if cookies is None:
        return {"status": "expired", "nickname": None}

    async with new_mp_client() as http:
        ask = (await http.get(
            _QR, params={"action": "ask", "token": "", "lang": "zh_CN", "f": "json", "ajax": 1},
            headers={"Cookie": cookies},
        )).json()
        status = ask.get("status", 0)
        if status != 1:
            return {"status": "scanned" if status in (4, 6) else "waiting", "nickname": None}

        biz = await http.post(
            _BIZLOGIN, params={"action": "login"},
            data={"userlang": "zh_CN", "redirect_url": "", "login_type": 3, "token": "",
                  "lang": "zh_CN", "f": "json", "ajax": 1},
            headers={"Cookie": cookies},
        )
        biz_json = biz.json()
        if biz_json.get("base_resp", {}).get("ret", 0) != 0:
            return {"status": "failed", "nickname": None}
        redirect = biz_json.get("redirect_url", "")
        token = _extract_token(redirect)
        if not token:
            return {"status": "failed", "nickname": None}
        long_cookies = _merge_cookies(cookies, biz.headers.get_list("set-cookie"))

        info = (await http.get(
            _INFO, params={"action": "info", "token": token, "lang": "zh_CN", "f": "json", "ajax": 1},
            headers={"Cookie": long_cookies},
        )).json()
        nickname = info.get("nick_name") or info.get("user_info", {}).get("nick_name") or "公众号"
        avatar = info.get("head_img")

    cred = WechatCredential(
        user_id=user_id,
        token=crypto.encrypt(token),
        cookies=crypto.encrypt(long_cookies),
        nickname=nickname,
        avatar=avatar,
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=4),
        status="active",
    )
    db.add(cred)
    await db.commit()
    await session_store.delete(session_id)
    return {"status": "confirmed", "nickname": nickname}


def _extract_token(redirect_url: str) -> str:
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(redirect_url).query)
    vals = q.get("token")
    return vals[0] if vals else ""


def _merge_cookies(base: str, set_cookies: list[str]) -> str:
    """把 bizlogin 的 set-cookie 合并进已有 cookie 串。"""
    jar: dict[str, str] = {}
    for pair in base.split(";"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            jar[k.strip()] = v.strip()
    for sc in set_cookies:
        first = sc.split(";")[0]
        if "=" in first:
            k, v = first.split("=", 1)
            jar[k.strip()] = v.strip()
    return "; ".join(f"{k}={v}" for k, v in jar.items())
