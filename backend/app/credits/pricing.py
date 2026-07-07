import math

from app.core.config import get_settings


def tokens_to_credits(total_tokens: int) -> int:
    s = get_settings()
    credits = math.ceil(max(0, total_tokens) / s.tokens_per_credit)
    return max(credits, s.min_charge)


def quota_for_plan(plan: str) -> int:
    s = get_settings()
    return s.subscribed_monthly_quota if plan == "subscribed" else s.free_monthly_quota
