"""Export the FastAPI app's OpenAPI document to stdout.

Used by `web` codegen (npm run codegen) to produce TypeScript types
without requiring the server to be running. See spec §3.

This script does NOT connect to the database, fetch from the network,
or call any external service — `app.openapi()` is pure introspection
over the registered routes and Pydantic schemas. The env-var defaults
below mirror `tests/conftest.py` so `app.main` is importable without
requiring a real `.env` file.
"""

from __future__ import annotations

import json
import os

# Satisfy app.config import-time validation without requiring a real .env.
# These values are NEVER used at runtime — the script doesn't open DB
# connections or verify JWTs.
os.environ.setdefault("NEXTAUTH_SECRET", "codegen-placeholder-not-for-runtime-xxxx")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DASHBOARD_DATA_DIR", "/tmp/codegen-placeholder")  # noqa: S108 — placeholder; never used at runtime (script makes no fs calls)

from app.main import app  # noqa: E402 — imports MUST follow env setdefault


def main() -> None:
    print(json.dumps(app.openapi(), indent=2))


if __name__ == "__main__":
    main()
