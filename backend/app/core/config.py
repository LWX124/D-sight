from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://dsight:dsight@localhost:5434/dsight"
    jwt_secret: str = "dev-secret"
    jwt_refresh_secret: str = "dev-refresh-secret"
    access_token_ttl_min: int = 15
    refresh_token_ttl_days: int = 30
    email_backend: str = "console"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-pro"
    bocha_api_key: str = ""
    fake_llm: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
