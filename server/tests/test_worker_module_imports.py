"""Pin the explicit-import contract at the worker entry point.

Regression guard for a production bug discovered during a Playwright
demo on 2026-05-18: `app.workers.worker` previously imported only
`run_propagate` and `orphan_sweeper` from `app.workers.tasks`, which
in turn imported only the `Run` model. The `User` and `MemoryEntry`
classes never entered `Base.metadata` in the worker process, so
SQLAlchemy could not resolve `runs.user_id`'s foreign key to `users.id`
and raised `NoReferencedTableError` on the worker's first flush.

The bug was latent since Wave 2 (PR #2) shipped the worker. It was
masked from CI because `server/tests/conftest.py` pre-imports all
three model modules; any `db_session` fixture user inherits the full
metadata. Production startup has no such fixture.

This test pins the explicit imports at the worker entry point so the
regression cannot recur silently. It is intentionally a source-string
inspection rather than a behavioral test — clearing `Base.metadata`
mid-test or running an isolated subprocess would be heavyweight for
what is fundamentally an import-list contract.
"""

import inspect


def test_worker_entry_point_imports_user_model():
    from app.workers import worker as worker_module
    src = inspect.getsource(worker_module)
    assert "from app.models import user" in src or "app.models.user" in src, (
        "app/workers/worker.py must explicitly import app.models.user — "
        "without it, the worker's first flush raises NoReferencedTableError "
        "on Run.user_id's FK to users.id."
    )


def test_worker_entry_point_imports_memory_entry_model():
    from app.workers import worker as worker_module
    src = inspect.getsource(worker_module)
    assert (
        "from app.models import memory_entry" in src
        or "app.models.memory_entry" in src
    ), (
        "app/workers/worker.py must explicitly import app.models.memory_entry "
        "so memory_mirror.sync_user's post-run flush has memory_entries in "
        "Base.metadata. Symptom on pre-fix: NoReferencedTableError on first "
        "successful run's mirror sync."
    )


def test_worker_entry_point_imports_run_model():
    from app.workers import worker as worker_module
    src = inspect.getsource(worker_module)
    # Run is allowed to enter via the tasks.py import chain (tasks.py
    # imports Run at line 20). Either path is acceptable as long as Run
    # ends up in Base.metadata when the worker boots.
    assert (
        "from app.models import run" in src
        or "app.models.run" in src
        or "from app.workers.tasks import" in src
    ), (
        "app/workers/worker.py must register the Run model somehow — "
        "via direct app.models.run import or via the tasks.py import chain."
    )
