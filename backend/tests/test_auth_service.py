import pytest
from sqlalchemy import select

from app.auth import service
from app.auth.models import User, VerificationCode


async def _get_code(db, email: str) -> str:
    row = await db.scalar(
        select(VerificationCode)
        .where(VerificationCode.email == email)
        .order_by(VerificationCode.created_at.desc())
        .limit(1)
    )
    return row.code


async def test_register_full_flow(db_session):
    email = "svc-flow@test.dev"
    await service.request_code(db_session, email)
    code = await _get_code(db_session, email)
    user = await service.register(db_session, email, code, "pw-123456")
    assert isinstance(user, User) and user.email == email

    fetched = await service.login(db_session, email, "pw-123456")
    assert fetched.id == user.id


async def test_request_code_rate_limited(db_session):
    email = "svc-rate@test.dev"
    await service.request_code(db_session, email)
    with pytest.raises(service.AuthError) as exc:
        await service.request_code(db_session, email)
    assert exc.value.status == 429


async def test_register_wrong_code_rejected(db_session):
    email = "svc-wrong@test.dev"
    await service.request_code(db_session, email)
    with pytest.raises(service.AuthError) as exc:
        await service.register(db_session, email, "000000", "pw-123456")
    assert exc.value.status == 400


async def test_register_duplicate_email_rejected(db_session):
    email = "svc-dup@test.dev"
    await service.request_code(db_session, email)
    code = await _get_code(db_session, email)
    await service.register(db_session, email, code, "pw-123456")

    # register checks duplicate email before the code, so a second register for the
    # same email returns 409 immediately (re-requesting a code here would hit the
    # 60s rate limit and never reach register).
    with pytest.raises(service.AuthError) as exc:
        await service.register(db_session, email, code, "pw-abcdef")
    assert exc.value.status == 409


async def test_login_wrong_password_rejected(db_session):
    email = "svc-badpw@test.dev"
    await service.request_code(db_session, email)
    code = await _get_code(db_session, email)
    await service.register(db_session, email, code, "pw-123456")
    with pytest.raises(service.AuthError) as exc:
        await service.login(db_session, email, "wrong")
    assert exc.value.status == 401
