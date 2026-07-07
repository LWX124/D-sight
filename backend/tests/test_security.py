import datetime as dt

import jwt
import pytest

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("s3cret-pw")
    assert h != "s3cret-pw"
    assert verify_password("s3cret-pw", h)
    assert not verify_password("wrong", h)


def test_access_token_roundtrip():
    token = create_access_token("user-123")
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["type"] == "access"


def test_refresh_token_has_jti_and_expiry():
    token, jti, expires = create_refresh_token("user-123")
    payload = decode_token(token, refresh=True)
    assert payload["jti"] == jti
    assert len(jti) == 32
    assert expires > dt.datetime.now(dt.UTC) + dt.timedelta(days=29)


def test_token_type_mismatch_rejected():
    access = create_access_token("u")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(access, refresh=True)


def test_forged_token_rejected():
    forged = jwt.encode({"sub": "u", "type": "access"}, "other-secret", algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(forged)
