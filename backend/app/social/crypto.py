from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import get_settings

_DEFAULT_KEY = "ZHNpZ2h0LXNvY2lhbC1kZXYtZmVybmV0LWtleS0zMmI="


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().social_encryption_key.encode()
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def assert_prod_key_configured() -> None:
    s = get_settings()
    if s.app_env == "prod" and s.social_encryption_key == _DEFAULT_KEY:
        raise RuntimeError(
            "生产环境必须设置 SOCIAL_ENCRYPTION_KEY（当前为提交在仓库的默认 dev key，"
            "用它加密微信凭证等同明文）。"
        )
