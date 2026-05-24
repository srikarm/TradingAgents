from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    nextauth_secret: str
    database_url: str
    dashboard_data_dir: Path
    legacy_results_dir: Path | None = None
    jwt_algorithm: str = "HS256"
    jwt_audience: str | None = None
    max_tail_bytes: int = 64 * 1024

    # Wave 2
    redis_url: str = "redis://localhost:6379/0"
    heartbeat_interval_seconds: int = 30
    orphan_threshold_seconds: int = 600  # 10 minutes
    queued_threshold_seconds: int = 1800  # 30 minutes — stuck QUEUED → FAILED
    default_llm_provider: str = "openai"
    default_deep_think_llm: str = "gpt-5.4"
    default_quick_think_llm: str = "gpt-5.4-mini"
    default_max_debate_rounds: int = 1
    default_max_risk_discuss_rounds: int = 1

    # Wave 3
    price_cache_ttl_seconds: int = 86_400  # 24h

    # Wave 5.4 — Notifications.
    # public_base_url is the origin used to build absolute /signals links in
    # notification payloads (e.g. https://tradix.axiara.ai). sendgrid_api_key is
    # the transactional-email provider key; when unset the notification system
    # uses the logging-stub adapter (no real sends) so the spine works without
    # external provisioning. notify_from_email is the verified sender address
    # (must be on a SendGrid-authenticated domain).
    public_base_url: str = "http://localhost:3000"
    sendgrid_api_key: str | None = None
    notify_from_email: str = "signals@axiara.ai"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
