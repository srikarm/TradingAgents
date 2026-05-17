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
    orphan_sweeper_interval_seconds: int = 300  # 5 minutes
    default_llm_provider: str = "openai"
    default_deep_think_llm: str = "gpt-5.4"
    default_quick_think_llm: str = "gpt-5.4-mini"
    default_max_debate_rounds: int = 1
    default_max_risk_discuss_rounds: int = 1

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
