"""arq worker entrypoint.

Run with: ``uv run arq app.workers.worker.WorkerSettings``
"""

from __future__ import annotations

from arq.cron import cron

from app.config import get_settings

# Register every ORM model with Base.metadata BEFORE the worker issues any
# flush. `tasks.py` writes to `runs`, whose user_id FK points at `users`;
# without User imported, SQLAlchemy raises NoReferencedTableError on the
# first commit. memory_mirror writes to memory_entries during the post-run
# sync. The api process gets this for free via router loading; the worker
# entry point has to be explicit.
from app.models import memory_entry as _memory_entry  # noqa: F401
from app.models import run as _run  # noqa: F401
from app.models import user as _user  # noqa: F401
from app.services.redis_pool import get_redis_settings
from app.workers.tasks import orphan_sweeper, run_propagate


class WorkerSettings:
    functions = [run_propagate]
    cron_jobs = [
        cron(
            orphan_sweeper,
            minute=set(range(0, 60, 5)),  # every 5 minutes
        )
    ]
    redis_settings = get_redis_settings()
    max_jobs = 1  # v1: one run at a time per worker process
    job_timeout = 60 * 60  # 1 hour cap on a single propagate
