import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.aihot.models import ProviderCallLog, ProviderRawRecord
from app.social.provider_audit import audited_provider_call


class _RawProvider:
    def __init__(self, secret: str):
        self._api_key = secret
        self._records = [
            {
                "platform": "wechat",
                "operation": "/provider/search",
                "payload": {
                    "data": {"name": "safe", "access_token": secret},
                    "authorization": f"Bearer {secret}",
                },
            }
        ]

    def drain_raw_records(self):
        records, self._records = self._records, []
        return records


@pytest.mark.asyncio
async def test_provider_audit_is_bounded_and_redacts_raw_secrets(db_session):
    secret = f"secret-{uuid.uuid4().hex}"
    operation = f"search-{uuid.uuid4().hex}"
    provider = _RawProvider(secret)

    result = await audited_provider_call(
        provider_client=provider,
        provider="redfox",
        platform="wechat",
        endpoint="publisher-search",
        operation=operation,
        call=lambda: _return([1, 2]),
        audit_db=db_session,
    )
    await db_session.flush()

    assert result == [1, 2]
    call = await db_session.scalar(
        select(ProviderCallLog).where(ProviderCallLog.operation == operation)
    )
    raw = await db_session.scalar(
        select(ProviderRawRecord).where(
            ProviderRawRecord.operation == "/provider/search"
        )
    )
    now = datetime.now(timezone.utc)
    assert call.status == "success" and call.response_size == 2
    assert raw.payload == {
        "data": {"name": "safe", "access_token": "[REDACTED]"},
        "authorization": "[REDACTED]",
    }
    assert now + timedelta(days=6, hours=23) < raw.expires_at <= now + timedelta(days=7)
    assert secret not in str(raw.payload)


@pytest.mark.asyncio
async def test_provider_audit_records_failure_without_secret(db_session):
    secret = f"secret-{uuid.uuid4().hex}"
    operation = f"detail-{uuid.uuid4().hex}"

    async def fail():
        raise RuntimeError(f"token={secret}")

    with pytest.raises(RuntimeError):
        await audited_provider_call(
            provider_client=_RawProvider(secret),
            provider="redfox",
            platform="xiaohongshu",
            endpoint="item-detail",
            operation=operation,
            call=fail,
            audit_db=db_session,
        )
    await db_session.flush()
    call = await db_session.scalar(
        select(ProviderCallLog).where(ProviderCallLog.operation == operation)
    )
    assert call.status == "failed"
    assert call.error_code == "RuntimeError"
    assert secret not in call.error_message


async def _return(value):
    return value
