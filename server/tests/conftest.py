import os

os.environ.setdefault("NEXTAUTH_SECRET", "test-secret-do-not-use-in-prod-xxxxxxxx")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DASHBOARD_DATA_DIR", "/tmp/trading-test")
