def test_redis_settings_parses_url(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", "x")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DASHBOARD_DATA_DIR", "/tmp/x")
    monkeypatch.setenv("REDIS_URL", "redis://my-redis:6380/2")
    from app.config import get_settings
    from app.services.redis_pool import get_redis_settings

    get_settings.cache_clear()
    settings = get_redis_settings()
    assert settings.host == "my-redis"
    assert settings.port == 6380
    assert settings.database == 2


def test_redis_settings_defaults_to_localhost(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", "x")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DASHBOARD_DATA_DIR", "/tmp/x")
    monkeypatch.delenv("REDIS_URL", raising=False)
    from app.config import get_settings
    from app.services.redis_pool import get_redis_settings

    get_settings.cache_clear()
    settings = get_redis_settings()
    assert settings.host == "localhost"
    assert settings.port == 6379
    assert settings.database == 0
