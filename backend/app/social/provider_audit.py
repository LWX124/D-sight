"""Durable, secret-safe audit records for social provider calls."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime, timezone
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.aihot.models import ProviderCallLog, ProviderRawRecord
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.social.retention import PROVIDER_RAW_RETENTION

logger = logging.getLogger(__name__)

T = TypeVar("T")
_REDACTED = "[REDACTED]"
_SECRET_KEYS = {
    "apikey",
    "authorization",
    "cookie",
    "password",
    "redfoxapikey",
    "refreshtoken",
    "secret",
    "setcookie",
    "token",
    "accesstoken",
}
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(api[_-]?key|authorization|cookie|password|secret|token)"
    r"(\s*[:=]\s*)([^\s,;&]+)"
)


def provider_audit_name(provider: object) -> str:
    """Return the stable provider identifier used by the audit tables."""
    names = {
        "RedFoxProvider": "redfox",
        "WechatMpProvider": "wechat_mp",
        "WeiboProvider": "weibo",
    }
    return names.get(type(provider).__name__, type(provider).__name__.lower())


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def sanitize_provider_payload(value: Any, secrets: Iterable[str] = ()) -> Any:
    """Recursively redact credential-shaped response fields before persistence."""
    secret_values = tuple(secret for secret in secrets if secret)
    if isinstance(value, dict):
        return {
            str(key): (
                _REDACTED
                if _normalized_key(key) in _SECRET_KEYS
                else sanitize_provider_payload(item, secret_values)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_provider_payload(item, secret_values) for item in value]
    if isinstance(value, tuple):
        return [sanitize_provider_payload(item, secret_values) for item in value]
    if isinstance(value, str):
        for secret in secret_values:
            value = value.replace(secret, _REDACTED)
        return _SECRET_ASSIGNMENT.sub(
            lambda match: f"{match.group(1)}{match.group(2)}{_REDACTED}",
            value,
        )
    return value


def redact_secret_text(error: Exception | str, secrets: Iterable[str] = ()) -> str:
    """Bound an error message and remove configured or credential-shaped values."""
    message = str(error)
    for secret in secrets:
        if secret:
            message = message.replace(secret, _REDACTED)
    message = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}{_REDACTED}", message)
    return message[:500]


def _provider_secrets(provider: object | None) -> tuple[str, ...]:
    if provider is None:
        return ()
    values = []
    for attribute in ("_api_key", "api_key", "_cookies", "cookies", "_token", "token"):
        value = getattr(provider, attribute, None)
        if isinstance(value, str) and value:
            values.append(value)
    return tuple(values)


def _response_size(value: Any) -> int | None:
    if isinstance(value, list | tuple | set | dict | str | bytes):
        return len(value)
    return 1 if value is not None else None


async def stage_provider_audit(
    db: AsyncSession,
    *,
    provider: str,
    platform: str,
    endpoint: str,
    operation: str,
    status: str,
    elapsed_ms: int,
    response_size: int | None = None,
    error: Exception | str | None = None,
    raw_records: Iterable[dict[str, Any]] = (),
    secrets: Iterable[str] = (),
    estimated_cost: float | None = None,
    now: datetime | None = None,
) -> None:
    """Stage one logical call and its bounded raw responses in ``db``."""
    captured_at = now or datetime.now(timezone.utc)
    db.add(
        ProviderCallLog(
            provider=provider,
            platform=platform,
            endpoint=endpoint,
            operation=operation,
            status=status,
            elapsed_ms=elapsed_ms,
            response_size=response_size,
            error_message=redact_secret_text(error, secrets) if error else None,
            error_code=type(error).__name__ if isinstance(error, Exception) else None,
            cache_hit=False,
            estimated_cost=estimated_cost,
        )
    )
    for record in raw_records:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        db.add(
            ProviderRawRecord(
                provider=provider,
                platform=str(record.get("platform") or platform),
                operation=str(record.get("operation") or operation),
                payload=sanitize_provider_payload(payload, secrets),
                expires_at=captured_at + PROVIDER_RAW_RETENTION,
            )
        )


async def audited_provider_call(
    *,
    provider_client: object | None,
    provider: str,
    platform: str,
    endpoint: str,
    operation: str,
    call: Callable[[], Awaitable[T]],
    audit_db: AsyncSession | None = None,
    estimated_cost: float | None = None,
) -> T:
    """Run a provider call and durably audit success or failure.

    Production callers use a short independent transaction so a failed content
    write cannot erase the evidence of the upstream call. Tests and batch flows
    may pass ``audit_db`` to stage the same records in an existing transaction.
    Audit persistence is best-effort and never changes provider behavior.
    """
    started = time.perf_counter()
    result: T | None = None
    error: Exception | None = None
    try:
        result = await call()
        return result
    except Exception as exc:
        error = exc
        raise
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        drain = getattr(provider_client, "drain_raw_records", None)
        raw_records = drain() if callable(drain) else []
        secrets = _provider_secrets(provider_client)
        cost = estimated_cost
        if cost is None and provider == "redfox":
            cost = get_settings().aihot_provider_call_cost
        try:
            if audit_db is not None:
                await stage_provider_audit(
                    audit_db,
                    provider=provider,
                    platform=platform,
                    endpoint=endpoint,
                    operation=operation,
                    status="failed" if error else "success",
                    elapsed_ms=elapsed_ms,
                    response_size=_response_size(result),
                    error=error,
                    raw_records=raw_records,
                    secrets=secrets,
                    estimated_cost=cost,
                )
            else:
                async with get_sessionmaker()() as db:
                    await stage_provider_audit(
                        db,
                        provider=provider,
                        platform=platform,
                        endpoint=endpoint,
                        operation=operation,
                        status="failed" if error else "success",
                        elapsed_ms=elapsed_ms,
                        response_size=_response_size(result),
                        error=error,
                        raw_records=raw_records,
                        secrets=secrets,
                        estimated_cost=cost,
                    )
                    await db.commit()
        except Exception:
            logger.exception(
                "provider audit persistence failed: %s/%s/%s",
                provider,
                platform,
                operation,
            )
