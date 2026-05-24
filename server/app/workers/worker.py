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
from app.models import watchlist as _watchlist  # noqa: F401  # Wave 5.2 — monitor cron reads watchlist_items
from app.models import notification as _notification  # noqa: F401  # Wave 5.4 — sweep reads monitor_batches + notifications
from app.services.monitor import monitor_tick
from app.services.notifications import notification_sweep
from app.services.redis_pool import get_redis_settings
from app.workers.tasks import orphan_sweeper, run_propagate


class WorkerSettings:
    functions = [run_propagate]
    cron_jobs = [
        cron(
            orphan_sweeper,
            minute=set(range(0, 60, 5)),  # every 5 minutes
        ),
        # Wave 5.2 — Monitor cron: fires at :00, :15, :30, :45 of every hour.
        # The 15-min window inside find_due_users matches this cadence so
        # every enabled user gets exactly one briefing per local day.
        cron(monitor_tick, minute={0, 15, 30, 45}),
        # Wave 5.4 — Notification sweep: fires at :05, :20, :35, :50 (offset
        # from monitor_tick) so a batch has time to start completing. Recurring
        # + day-wide so a long 10-ticker batch finishing late is still caught.
        cron(notification_sweep, minute={5, 20, 35, 50}),
    ]
    redis_settings = get_redis_settings()
    max_jobs = 1  # v1: one run at a time per worker process
    job_timeout = 60 * 60  # 1 hour cap on a single propagate
