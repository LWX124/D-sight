"""Provider selection and capability validation."""

from typing import Any

from app.social.providers.base import SocialProvider
from app.social.providers.redfox import RedFoxProvider
from app.social.providers.wechat_mp import WechatMpProvider
from app.social.providers.weibo import WeiboProvider

SUPPORTED_PLATFORMS = frozenset({"wechat", "weibo", "xiaohongshu", "bilibili"})


def get_provider(platform: str, settings: Any) -> SocialProvider:
    """Return the configured provider for a normalized platform name."""
    normalized = platform.strip().lower()
    if normalized not in SUPPORTED_PLATFORMS:
        raise ValueError(f"unsupported social platform: {platform}")
    if normalized == "weibo":
        return WeiboProvider()
    api_key = str(getattr(settings, "redfox_api_key", "") or "").strip()
    if api_key:
        return RedFoxProvider(api_key=api_key)
    if normalized == "wechat":
        return WechatMpProvider()
    raise ValueError(f"{normalized} requires REDFOX_API_KEY")
