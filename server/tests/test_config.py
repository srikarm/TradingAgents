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
