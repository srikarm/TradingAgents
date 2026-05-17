import subprocess
from pathlib import Path


def test_alembic_upgrade_head(tmp_path: Path):
    """`alembic upgrade head` against a fresh sqlite db must succeed."""
    db_file = tmp_path / "mig.db"
    env = {
        "PATH": _path_env(),
        "NEXTAUTH_SECRET": "test-secret-do-not-use-in-prod-xxxxxxxx",
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_file}",
        "DASHBOARD_DATA_DIR": str(tmp_path),
    }
    server_dir = Path(__file__).resolve().parents[1]
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=server_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert db_file.exists()


def _path_env() -> str:
    import os

    return os.environ["PATH"]
