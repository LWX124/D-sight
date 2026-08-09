import datetime as dt
import html
import logging
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

from selectolax.parser import HTMLParser

from app.social.weibo.errors import InvalidWeiboPayloadError

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WeiboProfile:
    uid: str
    name: str
    avatar: str | None
    description: str | None
    container_id: str


@dataclass(frozen=True)
class RawWeiboPost:
    external_id: str
    bid: str
    content: str
    published_at: dt.datetime
    media: list[dict[str, str]]
    is_repost: bool = False
    is_pinned: bool = False


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidWeiboPayloadError(f"微博响应缺少有效的 {label}")
    return value


def html_to_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    tree = HTMLParser(value.replace("<br>", "\n").replace("<br/>", "\n"))
    text = tree.text(separator=" ", strip=True)
    return re.sub(r"[ \t\f\v]+", " ", html.unescape(text)).strip()


def parse_datetime(value: Any) -> dt.datetime:
    if isinstance(value, int | float):
        return dt.datetime.fromtimestamp(value, tz=dt.UTC)
    if not isinstance(value, str) or not value.strip():
        raise InvalidWeiboPayloadError("微博内容缺少发布时间")
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise InvalidWeiboPayloadError("微博发布时间格式无效") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def parse_profile(payload: Any, expected_uid: str) -> WeiboProfile:
    root = _mapping(payload, "根对象")
    data = _mapping(root.get("data"), "data")
    info = _mapping(data.get("userInfo"), "userInfo")
    uid = str(info.get("id") or info.get("idstr") or "")
    name = info.get("screen_name")
    if uid != expected_uid or not isinstance(name, str) or not name.strip():
        raise InvalidWeiboPayloadError("微博账号资料与请求 UID 不匹配")
    tabs = _mapping(data.get("tabsInfo"), "tabsInfo").get("tabs")
    if not isinstance(tabs, list):
        raise InvalidWeiboPayloadError("微博账号资料缺少内容容器")
    container_id = ""
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        candidate = tab.get("containerid")
        if isinstance(candidate, str) and (tab.get("tab_type") == "weibo" or "WEIBO" in candidate):
            container_id = candidate
            break
    if not container_id:
        raise InvalidWeiboPayloadError("微博账号资料缺少内容容器")
    avatar = info.get("profile_image_url") or info.get("avatar_hd")
    description = info.get("description")
    return WeiboProfile(
        uid=uid,
        name=name.strip(),
        avatar=avatar if isinstance(avatar, str) else None,
        description=description if isinstance(description, str) else None,
        container_id=container_id,
    )


def _media_from_mblog(mblog: dict[str, Any]) -> list[dict[str, str]]:
    media: list[dict[str, str]] = []
    pics = mblog.get("pics")
    if isinstance(pics, list):
        for pic in pics:
            if not isinstance(pic, dict):
                continue
            large = pic.get("large")
            url = large.get("url") if isinstance(large, dict) else None
            url = url or pic.get("url")
            if isinstance(url, str) and url:
                media.append({"type": "image", "url": url})
    page = mblog.get("page_info")
    if isinstance(page, dict) and page.get("type") in {"video", "live"}:
        urls = page.get("urls")
        video_url = None
        if isinstance(urls, dict):
            for key in ("mp4_720p_mp4", "mp4_hd_mp4", "mp4_ld_mp4"):
                if isinstance(urls.get(key), str):
                    video_url = urls[key]
                    break
        video_url = (
            video_url or page.get("media_info", {}).get("stream_url")
            if isinstance(page.get("media_info"), dict)
            else video_url
        )
        if isinstance(video_url, str) and video_url:
            item = {"type": "video", "url": video_url}
            poster = page.get("page_pic")
            if isinstance(poster, dict):
                poster = poster.get("url")
            if isinstance(poster, str) and poster:
                item["poster_url"] = poster
            media.append(item)
    return media


def parse_mblog(value: Any) -> RawWeiboPost:
    mblog = _mapping(value, "mblog")
    external_id = str(mblog.get("id") or mblog.get("idstr") or "")
    bid = str(mblog.get("bid") or external_id)
    if not external_id or not bid:
        raise InvalidWeiboPayloadError("微博内容缺少 ID")
    return RawWeiboPost(
        external_id=external_id,
        bid=bid,
        content=html_to_text(mblog.get("text_raw") or mblog.get("text")),
        published_at=parse_datetime(mblog.get("created_at")),
        media=_media_from_mblog(mblog),
        is_repost="retweeted_status" in mblog,
        is_pinned=mblog.get("isTop") in (True, 1, "1"),
    )


def parse_posts(payload: Any) -> list[RawWeiboPost]:
    root = _mapping(payload, "根对象")
    data = _mapping(root.get("data"), "data")
    cards = data.get("cards")
    if not isinstance(cards, list):
        raise InvalidWeiboPayloadError("微博列表缺少 cards")
    posts: list[RawWeiboPost] = []
    for card in cards:
        if not isinstance(card, dict) or "mblog" not in card:
            continue
        try:
            posts.append(parse_mblog(card["mblog"]))
        except InvalidWeiboPayloadError as exc:
            _log.warning("skipping malformed weibo card: %s", exc)
            continue
    return posts


def parse_status(payload: Any) -> RawWeiboPost:
    root = _mapping(payload, "根对象")
    value = root.get("data", root)
    return parse_mblog(value)


def parse_login(payload: Any) -> tuple[str | None, str | None, str | None]:
    root = _mapping(payload, "根对象")
    data = _mapping(root.get("data"), "data")
    if data.get("login") not in (True, 1):
        from app.social.weibo.errors import WeiboSessionExpiredError

        raise WeiboSessionExpiredError("微博登录态已失效")
    user = data.get("userInfo")
    if not isinstance(user, dict):
        user = {}
    uid = user.get("id") or user.get("idstr") or data.get("uid")
    name = user.get("screen_name") or data.get("nick")
    avatar = user.get("profile_image_url") or user.get("avatar_hd") or data.get("avatar")
    return (
        str(uid) if uid is not None else None,
        name if isinstance(name, str) else None,
        avatar if isinstance(avatar, str) else None,
    )
