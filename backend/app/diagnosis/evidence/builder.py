"""
EvidencePack Builder

构建 EvidencePack，集成 provider tracking 和 fallback 逻辑。
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

from .providers import PROVIDER_REGISTRY
from .schemas import (
    EVIDENCE_BLOCKS,
    EvidencePack, EvidenceBlock, EvidenceItem, EvidenceStatus,
    Instrument,
)


class ProviderAttempt:
    """Provider 尝试记录"""
    def __init__(
        self,
        block_id: str,
        attempt_number: int,
        provider: str,
        status: str,
        latency_ms: float,
        error: Optional[str] = None,
    ):
        self.block_id = block_id
        self.attempt_number = attempt_number
        self.provider = provider
        self.status = status
        self.latency_ms = latency_ms
        self.error = error
        self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            'block_id': self.block_id,
            'attempt_number': self.attempt_number,
            'provider': self.provider,
            'status': self.status,
            'latency_ms': self.latency_ms,
            'error': self.error,
            'timestamp': self.timestamp.isoformat(),
        }


class EvidencePackBuilder:
    """
    EvidencePack 构建器

    负责从 provider 获取数据，构建 EvidencePack。
    支持 provider chain、fallback 和 last-good cache。
    """

    def __init__(self, instrument: Instrument, market: str):
        self.instrument = instrument
        self.market = market
        self.pack = EvidencePack(instrument=instrument)
        self.provider_attempts: list[ProviderAttempt] = []
        self._providers: dict[str, list] = {}  # block_id -> [provider_chain]
        self._unsupported_blocks: set[str] = set()

    def register_provider_chain(self, block_id: str, providers: list):
        """
        注册 provider chain

        Args:
            block_id: 证据块 ID
            providers: provider 列表，按优先级排序
        """
        self._providers[block_id] = providers

    def mark_not_supported(self, block_id: str) -> None:
        """Record an explicit market capability decision."""
        self._unsupported_blocks.add(block_id)

    async def _fetch_block(self, block_id: str):
        """
        获取单个证据块

        按 provider chain 依次尝试，记录每次尝试。
        通过 pack API 更新块和指标。
        """
        providers = self._providers.get(block_id, [])

        if not providers:
            block = EvidenceBlock(block_id=block_id)
            if block_id in self._unsupported_blocks:
                block.status = EvidenceStatus.not_supported
                self.pack.add_block(block)
                return
            self.pack.add_block(block)
            self.pack.warnings.append(f"provider_unconfigured:{block_id}")
            return

        block = EvidenceBlock(block_id=block_id)
        primary_provider = providers[0].__name__

        for provider_index, provider_func in enumerate(providers):
            start_time = time.perf_counter()
            try:
                items = await provider_func(self.instrument)
                latency_ms = (time.perf_counter() - start_time) * 1000

                # 记录成功尝试
                self.provider_attempts.append(
                    ProviderAttempt(
                        block_id=block_id,
                        attempt_number=provider_index + 1,
                        provider=provider_func.__name__,
                        status='success',
                        latency_ms=latency_ms,
                    )
                )

                if not items:
                    if block_id not in self.pack.blocks:
                        self.pack.add_block(block)
                    return

                for item in items:
                    if provider_index > 0:
                        item.status = EvidenceStatus.fallback
                        item.fallback_from = primary_provider
                    if block.block_id not in self.pack.blocks:
                        self.pack.add_block(block)
                    self.pack.add_item_to_block(block.block_id, item)
                return

            except Exception as exc:
                latency_ms = (time.perf_counter() - start_time) * 1000

                # 记录失败尝试
                self.provider_attempts.append(
                    ProviderAttempt(
                        block_id=block_id,
                        attempt_number=provider_index + 1,
                        provider=provider_func.__name__,
                        status='failed',
                        latency_ms=latency_ms,
                        error=str(exc),
                    )
                )

        block.status = EvidenceStatus.fetch_failed
        if block.block_id not in self.pack.blocks:
            self.pack.add_block(block)

    async def fetch_evidence(self, blocks: list[str]) -> EvidencePack:
        """
        获取证据并构建 EvidencePack

        Args:
            blocks: 需要获取的证据块列表

        Returns:
            构建完成的 EvidencePack
        """
        await asyncio.gather(*(self._fetch_block(block_id) for block_id in blocks))

        # 同步 provider attempts 到 pack
        self.pack.provider_attempts = self.get_provider_attempts()

        # 更新质量指标（确保同步）
        self.pack._update_metrics()

        return self.pack

    def add_item(self, block_id: str, item: EvidenceItem):
        """手动添加证据项"""
        block = self.pack.get_block(block_id)
        if block is None:
            block = EvidenceBlock(block_id=block_id)
            self.pack.add_block(block)
        self.pack.add_item_to_block(block_id, item)

    def get_provider_attempts(self) -> list[dict]:
        """获取所有 provider 尝试记录"""
        return [attempt.to_dict() for attempt in self.provider_attempts]

    def to_json(self) -> str:
        """序列化为 JSON"""
        return self.pack.to_json()


def get_provider_chain(market: str, block_id: str) -> list:
    """获取 provider chain。无 provider 即返回空列表，不做兜底。"""
    return PROVIDER_REGISTRY.get(market, {}).get(block_id, [])


def create_evidence_pack_builder(instrument: Instrument) -> EvidencePackBuilder:
    """创建 EvidencePack 构建器并注册该市场的真实 provider。

    Phase 0 只有 A 股有个股数据源。其余市场（US/HK/JP/KR）**逐块标记
    `not_supported`**——这是"我们不支持"，与"抓取失败"是两件事，
    质量分里也按前者处理（不计入缺口）。
    """
    market = instrument.market.value
    builder = EvidencePackBuilder(instrument=instrument, market=market)

    market_providers = PROVIDER_REGISTRY.get(market, {})
    for block_id in EVIDENCE_BLOCKS:
        providers = market_providers.get(block_id)
        if providers:
            builder.register_provider_chain(block_id, providers)
        elif not market_providers:
            builder.mark_not_supported(block_id)

    return builder
