import pytest


def test_encrypt_decrypt_roundtrip():
    from app.social.crypto import decrypt, encrypt

    secret = "token=abc123; cookie=xyz"
    enc = encrypt(secret)
    assert enc != secret
    assert decrypt(enc) == secret


def test_encrypt_nondeterministic_but_decryptable():
    from app.social.crypto import decrypt, encrypt

    a = encrypt("same")
    b = encrypt("same")
    assert a != b  # Fernet 带随机 IV
    assert decrypt(a) == decrypt(b) == "same"


def test_assert_prod_key_guard(monkeypatch):
    from app.core import config
    from app.social.crypto import assert_prod_key_configured

    monkeypatch.setenv("APP_ENV", "prod")
    config.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            assert_prod_key_configured()

        monkeypatch.setenv("SOCIAL_ENCRYPTION_KEY", "y-different-custom-key-not-default-32b=")
        config.get_settings.cache_clear()
        assert_prod_key_configured()  # 不抛
    finally:
        config.get_settings.cache_clear()
