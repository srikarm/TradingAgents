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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
