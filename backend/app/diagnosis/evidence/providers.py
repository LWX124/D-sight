"""证据 provider：把 `app.marketdata` 的真实取值接入 EvidencePack。

这里是 diagnosis 与取数层之间唯一的适配面，只做三件事：
1. 调 marketdata（同步、阻塞）并放到线程里执行，避免堵住事件循环；
2. 把 `DataPoint` 翻译成 `EvidenceItem`（保留 source / as_of / unit / period / warnings）；
3. 把"拿不到"如实表达为状态，而不是补默认值——上游异常直接抛出，
   由 `EvidencePackBuilder` 记为 `fetch_failed`；口径已知缺失的字段显式标 `missing`。

只注册 A 股（CN）。港股/日韩/美股在 Phase 0 不提供个股证据，
由 `create_evidence_pack_builder` 统一标记 `not_supported`，而不是给一条假数据。
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Optional

from app.marketdata import (
    compute_technicals,
    get_daily_bars,
    get_events,
    get_financials,
    get_profile,
    get_quote,
    get_valuation,
)
from app.marketdata.schemas import DataPoint

from .schemas import EvidenceItem, EvidenceStatus, Instrument

# 行情类数据超过这个天数即视为过期。A 股长假（春节/国庆）最长停市约 9 个自然日，
# 取 10 天以免长假期间误报；warning 里带上真实 as_of 供人判断。
_STALE_AFTER_DAYS = 10

# 技术指标需要的历史长度：200 日均线 + 余量。
_TECHNICAL_LOOKBACK = 300


def _as_date(value) -> date:
    return value.date() if isinstance(value, datetime) else value


def _currency_of(unit: Optional[str]) -> Optional[str]:
    """A 股取值的计价货币。unit 形如 CNY / CNY/share / price 时为人民币。"""
    if unit is None:
        return None
    return "CNY" if unit == "price" or unit.startswith("CNY") else None


def _to_item(point: DataPoint, *, price_derived: bool = False) -> EvidenceItem:
    """DataPoint → EvidenceItem，溯源字段原样带过去。

    `price_derived=True` 的项会按 as_of 判定是否过期——行情陈旧必须显式暴露，
    否则下游会把上周的收盘价当成今天的价格用。
    """
    warnings = list(point.warnings)
    status = EvidenceStatus.available

    if price_derived:
        age = (date.today() - _as_date(point.as_of)).days
        if age > _STALE_AFTER_DAYS:
            status = EvidenceStatus.stale
            warnings.append(f"行情数据距今 {age} 天（as_of={point.as_of}），长假期间属正常")

    return EvidenceItem(
        evidence_id=point.key,
        status=status,
        value=point.value,
        source=point.source,
        as_of=point.as_of,
        fetched_at=datetime.now(timezone.utc),
        currency=_currency_of(point.unit),
        unit=point.unit,
        period=point.period,
        warnings=warnings,
    )


def _missing(evidence_id: str, reason: str) -> EvidenceItem:
    """已知拿不到的字段：显式缺失，附原因，绝不给占位值。"""
    return EvidenceItem(
        evidence_id=evidence_id,
        status=EvidenceStatus.missing,
        missing_reason=reason,
        fetched_at=datetime.now(timezone.utc),
    )


# --- CN providers -----------------------------------------------------------
#
# 每个 provider 都是同步 marketdata 调用的薄包装。marketdata 内部已对 akshare
# 做串行化 + 60s 备忘，所以 quote / daily_bars / technical 并发拉同一份日线
# 只会真正打一次上游。


async def cn_identity_provider(instrument: Instrument) -> list[EvidenceItem]:
    points = await asyncio.to_thread(get_profile, instrument.canonical_symbol)
    return [_to_item(p) for p in points.points.values()]


async def cn_quote_provider(instrument: Instrument) -> list[EvidenceItem]:
    """价格/成交量来自日线收盘，市值与 PE 来自估值接口。

    Phase 0 不接实时行情（东财 push2 实时推送域被出口代理拦截），
    因此 quote_price 是最近一个交易日的收盘价，该事实由 marketdata 写进 warning。
    """
    symbol = instrument.canonical_symbol
    quote, valuation = await asyncio.gather(
        asyncio.to_thread(get_quote, symbol),
        asyncio.to_thread(get_valuation, symbol),
    )

    items = [_to_item(p, price_derived=True) for p in quote.values()]

    for key, evidence_id in (("quote_market_cap", "quote_market_cap"),
                             ("valuation_pe", "quote_pe_ratio")):
        point = valuation.get(key)
        if point is None:
            continue
        # quote 块用 quote_pe_ratio 这个 id，值与来源仍是估值接口的那一条。
        items.append(_to_item(
            DataPoint(
                key=evidence_id,
                value=point.value,
                as_of=point.as_of,
                source=point.source,
                unit=point.unit,
                period=point.period,
                warnings=point.warnings,
            ),
            price_derived=True,
        ))

    return items


async def cn_daily_bars_provider(instrument: Instrument) -> list[EvidenceItem]:
    """最近一根日线的 OHLCV。完整序列不进 EvidencePack（体积过大且下游不消费）。"""
    bars = await asyncio.to_thread(get_daily_bars, instrument.canonical_symbol, lookback=_TECHNICAL_LOOKBACK)
    last = bars.bars[-1]

    fields = {
        "daily_bars_open": (last.open, "price"),
        "daily_bars_high": (last.high, "price"),
        "daily_bars_low": (last.low, "price"),
        "daily_bars_close": (last.close, "price"),
        "daily_bars_volume": (last.volume, "shares"),
    }
    return [
        _to_item(
            DataPoint(key=key, value=value, as_of=bars.as_of, source=bars.source, unit=unit),
            price_derived=True,
        )
        for key, (value, unit) in fields.items()
    ]


async def cn_technical_provider(instrument: Instrument) -> list[EvidenceItem]:
    """技术指标由本地日线计算。样本不足的指标由 marketdata 直接不产出。"""
    bars = await asyncio.to_thread(get_daily_bars, instrument.canonical_symbol, lookback=_TECHNICAL_LOOKBACK)
    points = compute_technicals(bars)
    return [_to_item(p, price_derived=True) for p in points.points.values()]


async def cn_fundamentals_provider(instrument: Instrument) -> list[EvidenceItem]:
    points = await asyncio.to_thread(get_financials, instrument.canonical_symbol)
    return [_to_item(p) for p in points.points.values()]


async def cn_valuation_provider(instrument: Instrument) -> list[EvidenceItem]:
    points = await asyncio.to_thread(get_valuation, instrument.canonical_symbol)
    items = [_to_item(p, price_derived=True) for p in points.points.values()]

    # EV/EBITDA 需要企业价值与 EBITDA，现有免费源都不直接给；自行拼装误差不可控，
    # 因此如实标缺失，让依赖它的指标不计算，而不是拿一个近似值冒充。
    items.append(_missing(
        "valuation_ev_ebitda",
        "免费数据源未提供企业价值/EBITDA，不做近似推导",
    ))
    return items


async def cn_events_provider(instrument: Instrument) -> list[EvidenceItem]:
    """分红/送转/最近披露日。未实施的预案由 marketdata 打上 warning 后原样带出。"""
    points = await asyncio.to_thread(get_events, instrument.canonical_symbol)
    return [_to_item(p) for p in points.points.values()]


CN_PROVIDERS: dict[str, list] = {
    "identity": [cn_identity_provider],
    "quote": [cn_quote_provider],
    "daily_bars": [cn_daily_bars_provider],
    "technical": [cn_technical_provider],
    "fundamentals": [cn_fundamentals_provider],
    "valuation": [cn_valuation_provider],
    "events": [cn_events_provider],
}

# 尚无真实数据源的块：news / ownership / market_context /
# capital_flow / portfolio_context。这里刻意不注册——builder 会给出
# `provider_unconfigured:<block>` 警告，块状态保持 missing。
PROVIDER_REGISTRY: dict[str, dict[str, list]] = {"CN": CN_PROVIDERS}
