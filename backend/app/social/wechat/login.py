import datetime as dt
import logging
import re
import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.social import crypto
from app.social.models import WechatCredential
from app.social.wechat import session_store
from app.social.wechat.client import new_mp_client
from app.social.wechat.errors import TransientMpError

_log = logging.getLogger(__name__)

_QR = "https://mp.weixin.qq.com/cgi-bin/scanloginqrcode"
_BIZLOGIN = "https://mp.weixin.qq.com/cgi-bin/bizlogin"
_HOME = "https://mp.weixin.qq.com/cgi-bin/home"


async def start_qrcode() -> tuple[str, str, bytes]:
    """取二维码 + 建 login session。返回 (session_id, mime, 图片字节)。

    微信要求先 bizlogin?action=startlogin 建立会话（下发 uuid cookie），
    getqrcode 才会返回图片；否则 200 空 body。
    """
    session_id = uuid.uuid4().hex
    now_ms = str(int(time.time() * 1000))
    async with new_mp_client() as http:
        start = await http.post(
            _BIZLOGIN, params={"action": "startlogin"},
            data={"userlang": "zh_CN", "redirect_url": "", "login_type": 3,
                  "sessionid": now_ms, "token": "", "lang": "zh_CN", "f": "json", "ajax": 1},
        )
        start.raise_for_status()
        r = await http.get(_QR, params={"action": "getqrcode", "random": now_ms})
        r.raise_for_status()
        if not r.content:
            raise TransientMpError("二维码接口返回空内容（可能被限流），请稍后重试")
        cookies = "; ".join(f"{k}={v}" for k, v in http.cookies.items())
        await session_store.save(session_id, cookies)
        return session_id, r.headers.get("content-type", "image/jpg"), r.content


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
            # 状态机对齐 mp.weixin：0 未扫码；2/3 二维码失效；4/6 已扫码待确认
            # （acct_size=0 表示该微信没有可登录的公众号）；5 未绑定邮箱。
            _log.info("wechat login ask: session=%s resp=%s", session_id, ask)
            if status in (2, 3):
                return {"status": "expired", "nickname": None}
            if status in (4, 6):
                if ask.get("acct_size", 0) >= 1:
                    return {"status": "scanned", "nickname": None}
                return {"status": "no_account", "nickname": None}
            if status == 5:
                return {"status": "no_email", "nickname": None}
            return {"status": "waiting", "nickname": None}

        biz = await http.post(
            _BIZLOGIN, params={"action": "login"},
            data={"userlang": "zh_CN", "redirect_url": "", "cookie_forbidden": 0,
                  "cookie_cleaned": 0, "plugin_used": 0, "login_type": 3, "token": "",
                  "lang": "zh_CN", "f": "json", "ajax": 1},
            headers={"Cookie": cookies},
        )
        biz_json = biz.json()
        if biz_json.get("base_resp", {}).get("ret", 0) != 0:
            _log.warning("wechat bizlogin failed: session=%s resp=%s", session_id, biz_json)
            return {"status": "failed", "nickname": None}
        redirect = biz_json.get("redirect_url", "")
        token = _extract_token(redirect)
        if not token:
            return {"status": "failed", "nickname": None}
        long_cookies = _merge_cookies(cookies, biz.headers.get_list("set-cookie"))
        nickname, avatar = await _fetch_account_info(http, token, long_cookies)

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


async def _fetch_account_info(http, token: str, cookies: str) -> tuple[str, str | None]:
    """从 mp 首页 HTML 提取昵称/头像（微信无 JSON 接口）。昵称仅展示用，失败不阻断登录。"""
    try:
        r = await http.get(
            _HOME, params={"t": "home/index", "token": token, "lang": "zh_CN"},
            headers={"Cookie": cookies},
        )
        html = r.text
        nick = re.search(r'wx\.cgiData\.nick_name\s*=\s*"([^"]+)"', html)
        head = re.search(r'wx\.cgiData\.head_img\s*=\s*"([^"]+)"', html)
        return (nick.group(1) if nick else "公众号"), (head.group(1) if head else None)
    except Exception:  # noqa: BLE001 — 展示信息抓取失败不能毁掉已成功的登录
        _log.warning("wechat fetch account info failed", exc_info=True)
        return "公众号", None


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
