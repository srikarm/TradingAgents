import os

from app.config import Settings


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", "abc")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DASHBOARD_DATA_DIR", "/tmp/x")
    s = Settings()
    assert s.nextauth_secret == "abc"
    assert s.database_url.startswith("sqlite+aiosqlite")
    assert str(s.dashboard_data_dir) == "/tmp/x"


def test_settings_missing_secret_raises(monkeypatch):
    monkeypatch.delenv("NEXTAUTH_SECRET", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DASHBOARD_DATA_DIR", "/tmp/x")
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings()


def test_settings_reads_redis_and_worker_config(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", "abc")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DASHBOARD_DATA_DIR", "/tmp/x")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("HEARTBEAT_INTERVAL_SECONDS", "10")
    monkeypatch.setenv("ORPHAN_THRESHOLD_SECONDS", "300")
    from app.config import Settings, get_settings
    get_settings.cache_clear()
    s = Settings()
    assert s.redis_url == "redis://localhost:6379/0"
    assert s.heartbeat_interval_seconds == 10
    assert s.orphan_threshold_seconds == 300


def test_settings_has_llm_provider_defaults(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", "abc")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DASHBOARD_DATA_DIR", "/tmp/x")
    from app.config import Settings, get_settings
    get_settings.cache_clear()
    s = Settings()
    assert s.default_llm_provider == "openai"
    assert s.default_deep_think_llm.startswith("gpt-")
    assert s.default_quick_think_llm.startswith("gpt-")
