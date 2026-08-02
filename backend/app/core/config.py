from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    database_url: str = "postgresql+asyncpg://dsight:dsight@localhost:5434/dsight"
    jwt_secret: str = "dev-secret"
    jwt_refresh_secret: str = "dev-refresh-secret"
    access_token_ttl_min: int = 15
    refresh_token_ttl_days: int = 30
    email_backend: str = "console"
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-pro"
    bocha_api_key: str = ""
    fake_llm: bool = False
    tokens_per_credit: int = 1000
    free_monthly_quota: int = 100
    subscribed_monthly_quota: int = 2000
    min_charge: int = 1
    redis_url: str = "redis://localhost:6381/0"
    rate_limit_per_min: int = 20
    embedding_backend: str = "fake"        # fake / siliconflow
    siliconflow_api_key: str = ""
    embedding_model: str = "BAAI/bge-m3"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    kb_max_upload_mb: int = 10
    kb_backfill_delay_seconds: float = 2.0     # 正文抓取最小间隔（前后台共用限流器）
    kb_backfill_max_failures: int = 3          # 连续失败几篇后中止本批回填
    kb_max_documents_per_kb: int = 2000        # 单库文档数上限（含上传），admin 豁免
    kb_max_sources_per_user: int = 10          # 每用户订阅源总数上限，admin 豁免
    kb_backfill_batch_limit: int = 50          # 单次回填最多处理多少篇
    news_backend: str = "fake"
    # Fernet 密钥（base64 urlsafe 32 字节）。留空则用 dev 默认（仅测试/本地）。
    social_encryption_key: str = "ZHNpZ2h0LXNvY2lhbC1kZXYtZmVybmV0LWtleS0zMmI="
    social_poll_minutes: int = 30
    social_fetch_count: int = 20
    fund_arb_backend: str = "sina"
    fund_arb_snapshot_seconds: int = 20
    # 深度分析
    deep_analysis_analyst_model: str = "deepseek-v4-flash"
    deep_analysis_portfolio_model: str = "deepseek-v4-pro"
    deep_analysis_max_concurrency: int = 8
    deep_analysis_analyst_timeout_seconds: int = 45
    deep_analysis_task_timeout_seconds: int = 300
    deep_analysis_max_attempts: int = 3
    deep_analysis_cache_hours: int = 4
    deep_analysis_credits: int = 50
    deep_analysis_worker_enabled: bool = False
    deep_analysis_analysis_version: str = "v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
