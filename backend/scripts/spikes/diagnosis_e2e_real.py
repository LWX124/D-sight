"""真网端到端：600519 走完 EvidencePack → 指标 → 六维度 → 结论。

验收目标不是"跑通"，而是证明链路上**没有假数据**：
  1. 每个 available 证据项都带 source 与 as_of；
  2. 证据值来自上游，不等于历史硬编码占位（1800.0 / 180.0 等）；
  3. 非 A 股市场如实标 not_supported，而不是返回一条美股假报价。

用法：
    uv run python scripts/spikes/diagnosis_e2e_real.py [--symbol 600519] [--out <path.json>]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.diagnosis.evidence.builder import create_evidence_pack_builder  # noqa: E402
from app.diagnosis.evidence.providers import CN_PROVIDERS  # noqa: E402
from app.diagnosis.evidence.schemas import (  # noqa: E402
    EvidenceStatus,
    Instrument,
    Market,
    validate_evidence_pack,
)
from app.diagnosis.runner import DiagnosisRunner  # noqa: E402
from app.diagnosis.schemas import (  # noqa: E402
    DecisionProfileSchema,
    InvestmentHorizon,
    PositionType,
)

# 历史假实现里写死过的数字，出现即说明假 provider 复活了
FORBIDDEN_VALUES = {1800.0, 180.0, 1000000, 50000000, 0.15, 25.0, 55.0}


def build_instrument(symbol: str) -> Instrument:
    return Instrument(
        market=Market.CN,
        canonical_symbol=symbol,
        exchange="SSE" if symbol.startswith("6") else "SZSE",
        currency="CNY",
        timezone="Asia/Shanghai",
        original_input=symbol,
        normalization_method="code_pattern",
    )


async def fetch_pack(symbol: str):
    instrument = build_instrument(symbol)
    builder = create_evidence_pack_builder(instrument)
    return await builder.fetch_evidence(list(CN_PROVIDERS))


def check_provenance(pack) -> list[str]:
    """每个可用取值都必须能追溯，且不能是历史占位数字。"""
    problems: list[str] = []
    for block in pack.blocks.values():
        for item in block.items.values():
            if item.status not in (
                EvidenceStatus.available,
                EvidenceStatus.stale,
                EvidenceStatus.fallback,
            ):
                continue
            if not item.source:
                problems.append(f"{item.evidence_id} 缺少 source")
            if not item.as_of:
                problems.append(f"{item.evidence_id} 缺少 as_of")
            if isinstance(item.value, (int, float)) and item.value in FORBIDDEN_VALUES:
                problems.append(f"{item.evidence_id} 命中历史硬编码值 {item.value}")
    return problems


async def check_unsupported_market() -> list[str]:
    """美股在 Phase 0 无数据源，必须是 not_supported，不是假报价。"""
    us = Instrument(
        market=Market.US,
        canonical_symbol="AAPL",
        exchange="NASDAQ",
        currency="USD",
    )
    pack = await create_evidence_pack_builder(us).fetch_evidence(["quote", "fundamentals"])
    problems = []
    for block_id in ("quote", "fundamentals"):
        block = pack.get_block(block_id)
        if block is None or block.status is not EvidenceStatus.not_supported:
            status = block.status.value if block else "缺块"
            problems.append(f"US/{block_id} 状态为 {status}，应为 not_supported")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="600519")
    parser.add_argument("--out", default=None, help="把完整结果写入该 JSON 文件")
    args = parser.parse_args()

    pack = asyncio.run(fetch_pack(args.symbol))

    print(f"=== EvidencePack {args.symbol} ===")
    print(f"quality_score={pack.quality_score:.3f}  completeness={pack.completeness:.3f}")
    for block_id, block in pack.blocks.items():
        print(f"\n[{block_id}] status={block.status.value} completeness={block.completeness:.2f}")
        for item in block.items.values():
            if item.value is None:
                print(f"  - {item.evidence_id}: <{item.status.value}> {item.missing_reason or ''}")
                continue
            value = f"{item.value:.4g}" if isinstance(item.value, float) else item.value
            print(f"  - {item.evidence_id} = {value}  [{item.source} @ {item.as_of}]")

    problems = check_provenance(pack)
    problems += validate_evidence_pack(pack, "CN", "medium")
    problems += asyncio.run(check_unsupported_market())

    print("\n=== 诊断结论 ===")
    advice = DiagnosisRunner().run(
        pack,
        DecisionProfileSchema(
            position_status=PositionType.EMPTY,
            primary_horizon=InvestmentHorizon.MEDIUM,
        ),
    )
    conclusion = advice.conclusion
    print(f"action={conclusion.action}  confidence={advice.overall_confidence:.2f}")
    print(f"触发条件: {conclusion.triggering_conditions or '（指标不足，未产出）'}")
    print(f"失效条件: {conclusion.invalidating_conditions or '（指标不足，未产出）'}")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {"evidence_pack": pack.to_dict(), "advice": advice.to_dict(), "problems": problems},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"\n已写入 {out}")

    if problems:
        print("\n=== 未通过 ===")
        for problem in problems:
            print(f"  ✗ {problem}")
        return 1

    print("\n全部检查通过：无假数据，溯源完整。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
