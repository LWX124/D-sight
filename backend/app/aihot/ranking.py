"""Deterministic and replayable cross-platform AIHot ranking."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone

FORMULA_VERSION = "relative-v1"
WINDOW_HOURS = {"24h": 24, "3d": 72, "7d": 168}

# Used only to create a within-platform engagement signal. Absolute values never
# cross the platform boundary.
ENGAGEMENT_WEIGHTS = {
    "like": 1.0,
    "comment": 3.0,
    "share": 5.0,
    "collect": 2.0,
    "view": 0.01,
    "read": 0.005,
}


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def compute_freshness_score(published_at: datetime, now: datetime | None = None) -> float:
    """24-hour half-life, clamped so future timestamps do not score above 100."""
    current = _as_aware(now or datetime.now(timezone.utc))
    age_hours = max(0.0, (current - _as_aware(published_at)).total_seconds() / 3600)
    return 100.0 * (2 ** (-age_hours / 24.0))


def _engagement_signal(metrics: dict) -> float:
    weighted = sum(
        max(0.0, float(metrics.get(name) or 0)) * weight
        for name, weight in ENGAGEMENT_WEIGHTS.items()
    )
    return math.log1p(weighted)


def _platform_scores(items: list[dict]) -> dict[object, float]:
    grouped: dict[str, list[tuple[object, float]]] = defaultdict(list)
    for item in items:
        provider_rank = item.get("provider_rank")
        # Smaller provider rank is hotter. When unavailable, use the log-scaled
        # engagement signal. The result is converted to a percentile below.
        signal = -float(provider_rank) if provider_rank is not None else _engagement_signal(
            item.get("metrics", {})
        )
        grouped[item["platform"]].append((item["item_id"], signal))

    result: dict[object, float] = {}
    for entries in grouped.values():
        ordered = sorted(entries, key=lambda row: row[1])
        if len(ordered) == 1:
            result[ordered[0][0]] = 50.0
            continue
        denominator = len(ordered) - 1
        for index, (item_id, _signal) in enumerate(ordered):
            result[item_id] = 100.0 * index / denominator
    return result


def rank_items(
    items: list[dict],
    *,
    window: str,
    previous_ranks: dict[object, int] | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Rank one cumulative time window using saved real metrics.

    Each item needs ``item_id``, ``platform``, ``published_at`` and ``metrics``.
    ``provider_rank`` is optional. AI relevance is an admission decision made by
    the pipeline, never a heat-score input.
    """
    if window not in WINDOW_HOURS:
        raise ValueError(f"unsupported AIHot window: {window}")

    current = _as_aware(now or datetime.now(timezone.utc))
    max_age = WINDOW_HOURS[window]
    eligible = [
        item
        for item in items
        if 0 <= (current - _as_aware(item["published_at"])).total_seconds() / 3600 <= max_age
    ]
    if not eligible:
        return []

    platform_scores = _platform_scores(eligible)
    prior = previous_ranks or {}
    provisional: list[dict] = []
    for item in eligible:
        platform_score = platform_scores[item["item_id"]]
        freshness_score = compute_freshness_score(item["published_at"], current)
        base_score = 0.60 * platform_score + 0.25 * freshness_score + 0.15 * 50.0
        provisional.append(
            {
                **item,
                "platform_score": platform_score,
                "freshness_score": freshness_score,
                "base_score": base_score,
            }
        )

    provisional.sort(key=lambda row: (-row["base_score"], str(row["item_id"])))
    preliminary_rank = {row["item_id"]: index for index, row in enumerate(provisional, 1)}

    ranked: list[dict] = []
    for item in provisional:
        previous_rank = prior.get(item["item_id"])
        if previous_rank is None:
            momentum_score = 50.0
        else:
            movement = previous_rank - preliminary_rank[item["item_id"]]
            momentum_score = max(0.0, min(100.0, 50.0 + movement * 5.0))
        final_score = (
            0.60 * item["platform_score"]
            + 0.25 * item["freshness_score"]
            + 0.15 * momentum_score
        )
        ranked.append(
            {
                **item,
                "momentum_score": momentum_score,
                "aihot_score": final_score,
                "window": window,
                "formula_version": FORMULA_VERSION,
                "previous_rank": previous_rank,
            }
        )

    ranked.sort(key=lambda row: (-row["aihot_score"], str(row["item_id"])))
    for index, item in enumerate(ranked, 1):
        item["rank"] = index
        previous_rank = item["previous_rank"]
        item["rank_delta"] = None if previous_rank is None else previous_rank - index
        item.pop("base_score", None)
    return ranked
