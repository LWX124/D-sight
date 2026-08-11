"""Provider Adapter 基类和 DTO 定义。"""
from app.social.providers.base import (
    ItemDTO,
    MetricsDTO,
    PublisherDTO,
    SocialProvider,
)
from app.social.providers.registry import SUPPORTED_PLATFORMS, get_provider

__all__ = [
    "ItemDTO",
    "MetricsDTO",
    "PublisherDTO",
    "SUPPORTED_PLATFORMS",
    "SocialProvider",
    "get_provider",
]
