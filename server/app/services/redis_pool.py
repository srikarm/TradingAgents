"""arq Redis settings + connection pool helper.

The api process (enqueueing jobs) and the worker process (consuming them)
both share these settings.
"""

from __future__ import annotations

from urllib.parse import urlparse

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import get_settings


def get_redis_settings() -> RedisSettings:
    """Parse REDIS_URL into arq's RedisSettings."""
    raw = get_settings().redis_url
    parsed = urlparse(raw)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or "0"),
        password=parsed.password,
    )


async def get_redis_pool() -> ArqRedis:
    """Open a new arq pool. Caller is responsible for `.close()`."""
    return await create_pool(get_redis_settings())
