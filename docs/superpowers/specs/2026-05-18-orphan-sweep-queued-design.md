# `orphan_sweeper` QUEUED Sweep — Design

**Status:** Approved, awaiting implementation plan
**Date:** 2026-05-18
**Followup of:** PR #3 (Wave 2 — orphan_sweeper added) + v3+ followup #11 in the deferred list
**Independent of:** all in-flight work; main currently at `141efc6` (post-PR-#8 merge)
**Author:** erik

---

## 1. Problem

`orphan_sweeper` (`server/app/workers/tasks.py:250-270`) currently catches one failure mode: a worker that crashed mid-run. It looks for `Run.status == RUNNING AND Run.last_heartbeat_at < (now - orphan_threshold_seconds)` and marks those rows `FAILED` with `error_summary="worker_lost"`.

It does NOT catch the other failure mode: a worker that crashed BEFORE picking up the run from the arq queue, or an arq queue corruption that loses the job. These runs sit in `QUEUED` forever:

- `last_heartbeat_at` is `NULL` (only set on the QUEUED → RUNNING transition)
- `created_at` is the only signal we have
- Existing sweep's WHERE clause skips them

User-visible effect: the dashboard shows "Queued" indefinitely, with no Run record progression. Operators have no way to know if a run is "legitimately waiting" or "abandoned" without inspecting arq's Redis state.

The v3+ list captured this gap:

> orphan_sweeper sweep of stuck QUEUED runs

This spec extends `orphan_sweeper` with a second WHERE clause that catches stuck-QUEUED runs and gives them a definitive `FAILED` state.

---

## 2. Goal & non-goals

**Goal.** Detect and mark stuck-QUEUED runs as `FAILED` with a distinguishable `error_summary` ("`never_picked_up`"), inside the existing `orphan_sweeper` cron, using a new `queued_threshold_seconds` setting (default 30 min).

**Non-goals (deliberately).**

- **Fixing the pre-existing race in `run_propagate`** (`tasks.py:158` does `run.status = RunStatus.RUNNING` without checking the current status). With the 30-min threshold and arq's sub-second pickup latency the window is microscopic, but the race exists. Fix is a separate spec — guard with `if run.status != RunStatus.QUEUED: return`.
- **Tracking queue position** to inform threshold dynamically (e.g., "if N runs are queued ahead, scale the threshold"). YAGNI; the static 30 min default is correct for the dev/single-worker fork environment.
- **Different UI treatment** for the two failure modes (`worker_lost` vs `never_picked_up`). The frontend renders both as "Failed" with the `error_summary` shown in detail view. v3+ followup territory if/when it becomes a real concern.
- **Retry logic** for stuck-QUEUED runs. Marked `FAILED`; user re-launches manually. Auto-retry is its own spec.
- **arq introspection** to verify the run is actually gone from the queue before sweeping. Too tight a coupling to the queue backend; the time-based threshold is the right level of abstraction.

---

## 3. New setting

`server/app/config.py` Settings class gets a new field:

```python
queued_threshold_seconds: int = 1800  # 30 min — stuck QUEUED → FAILED
```

This sits alongside the existing:

```python
orphan_threshold_seconds: int = 600   # 10 min — stuck RUNNING → FAILED
```

Two independent settings because the two failure modes have different signal-noise profiles:
- RUNNING: heartbeat-based, fires every 30s; 10 min = 20 missed heartbeats = high confidence the worker is gone.
- QUEUED: time-based only (no heartbeat possible); needs more headroom because a legitimate backlog of queued runs (each ~5-15 min) could push a queue-tail entry past a short threshold.

30 min default tolerates a backlog of ~2-3 queued runs ahead. For deployments with concurrent workers or different latency profiles, the operator can tune.

---

## 4. Sweep change — two queries, one transaction

In `server/app/workers/tasks.py:orphan_sweeper`, after the existing RUNNING UPDATE, add a parallel QUEUED UPDATE:

```python
async def orphan_sweeper(ctx: dict) -> None:
    """Cron: mark stale `running` AND stale `queued` rows as failed.

    Two parallel sweeps:
    - RUNNING: heartbeat older than `orphan_threshold_seconds` → worker died mid-run
    - QUEUED:  created_at older than `queued_threshold_seconds` → worker never picked it up
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    running_threshold = now - timedelta(seconds=settings.orphan_threshold_seconds)
    queued_threshold = now - timedelta(seconds=settings.queued_threshold_seconds)

    async with _session_factory_for_worker() as session:
        running_result = await session.execute(
            update(Run)
            .where(
                Run.status == RunStatus.RUNNING,
                Run.last_heartbeat_at < running_threshold,
            )
            .values(
                status=RunStatus.FAILED,
                error_summary="worker_lost",
                completed_at=now,
            )
        )
        queued_result = await session.execute(
            update(Run)
            .where(
                Run.status == RunStatus.QUEUED,
                Run.created_at < queued_threshold,
            )
            .values(
                status=RunStatus.FAILED,
                error_summary="never_picked_up",
                completed_at=now,
            )
        )
        await session.commit()
        logger.info(
            "orphan_sweeper: marked %d stuck-running + %d stuck-queued run(s) failed",
            running_result.rowcount, queued_result.rowcount,
        )
```

### 4.1 Why two queries, not one OR

A combined `UPDATE ... WHERE (RUNNING AND heartbeat_stale) OR (QUEUED AND created_stale)` would let us set a single `error_summary` value, but we lose the failure-mode distinction. `"worker_lost"` and `"never_picked_up"` describe very different incidents to the operator triaging:
- `worker_lost`: the worker process died mid-execution (look at LLM API errors, OOM kills, segfaults).
- `never_picked_up`: the worker never started this job (look at arq queue state, worker registration, Redis connectivity).

Distinguishability beats one-query elegance here.

### 4.2 Why same transaction

The two UPDATEs run inside one `async with session_factory()`, one `commit()`. If either fails (DB connection drops mid-sweep), neither is partially applied. The log line reports both counts together so the operator sees the full sweep outcome.

---

## 5. Tests

Extend `server/tests/test_orphan_sweeper.py` with two new tests. Existing tests (`test_orphan_sweeper_marks_stale_running_as_failed`, `test_orphan_sweeper_ignores_terminal_runs`) cover the existing RUNNING path and the SUCCEEDED/FAILED non-transitions; they keep passing without modification.

### 5.1 `test_orphan_sweeper_marks_stale_queued_as_failed`

```python
@pytest.mark.asyncio
async def test_orphan_sweeper_marks_stale_queued_as_failed(db_session, monkeypatch):
    """Spec §3: a QUEUED run whose created_at is older than the
    queued threshold must be marked FAILED with error_summary=
    'never_picked_up'."""
    # Patch the factory + settings (mirror the existing test's pattern)
    # Insert a User
    # Insert a QUEUED Run with created_at = now - 1 hour
    #   (no last_heartbeat_at — it's NULL for QUEUED runs)
    # Run orphan_sweeper
    # Assert: status == FAILED, error_summary == "never_picked_up",
    #         completed_at is set, last_heartbeat_at remains NULL
```

### 5.2 `test_orphan_sweeper_ignores_fresh_queued`

```python
@pytest.mark.asyncio
async def test_orphan_sweeper_ignores_fresh_queued(db_session, monkeypatch):
    """A QUEUED run whose created_at is within the threshold window must
    stay QUEUED — false-positives would penalize legitimate backlog runs."""
    # Insert a QUEUED Run with created_at = now - 1 minute
    # Run orphan_sweeper
    # Assert: status remains QUEUED, error_summary stays NULL,
    #         completed_at stays NULL
```

### 5.3 No new test for legacy paths

The existing `test_orphan_sweeper_ignores_terminal_runs` already verifies that SUCCEEDED and FAILED rows are untouched (regardless of age). It doesn't specifically test QUEUED runs that already failed, but a row in any terminal state is skipped by both UPDATE WHERE clauses (`status == QUEUED` is False for terminal states). No coverage gap.

---

## 6. Files touched

| File | Change |
|------|--------|
| `server/app/config.py` | Add `queued_threshold_seconds: int = 1800` Settings field. |
| `server/app/workers/tasks.py` | Modify `orphan_sweeper` — add second UPDATE for stuck QUEUED, update docstring + log line. |
| `server/tests/test_orphan_sweeper.py` | Add 2 new tests (stale-queued, fresh-queued). |

No DB migration. No router/service/model change. No frontend. No alembic.

---

## 7. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| **Race condition**: sweep marks QUEUED → FAILED, then worker picks up the row and does `run.status = RUNNING` without status check. Row ends up RUNNING with `error_summary="never_picked_up"`. | Pre-existing race (the worker doesn't guard today). Documented as out of scope. Probability is microscopic with 30-min threshold + sub-second arq pickup. |
| **Legitimate backlog**: 5+ queued runs each taking 10 min means the last one waits 50 min and gets false-positive'd by the 30-min threshold. | Operator tunes `queued_threshold_seconds` higher if needed. Default reflects dev/single-worker assumptions. Documented in §3. |
| **Threshold tuning**: too short → false positives; too long → user sees stale Queued for an hour. | Configurable via env var. Default is the spec-recommended starting point. |
| **DB indexes**: the new `Run.status == QUEUED AND Run.created_at < ...` query needs index support. `Run.status` is already `index=True` (per `models/run.py`). `created_at` is server_default but NOT indexed. For the current single-table-scan + status filter, this is fine on dev DB sizes; a future migration could add an index if QUEUED row counts grow large. | Out of scope for now. Note in comments. |

---

## 8. Verification

The implementation is done when all of the following are true:

1. `cd server && uv run pytest tests/test_orphan_sweeper.py -v` shows 4 tests passing (2 existing + 2 new).
2. `cd server && uv run pytest -q` shows 146 tests pass (144 baseline + 2 new).
3. `grep -c "never_picked_up\|queued_threshold_seconds" server/app/workers/tasks.py server/app/config.py` returns at least 3 (one in config, two in tasks).
4. `git diff main..HEAD --name-only` shows exactly 4 files (spec + config + tasks + test_orphan_sweeper).
5. The new log line format mentions BOTH `stuck-running` and `stuck-queued` counts.
6. Existing 2 orphan_sweeper tests still pass without modification.

---

## 9. References

- v3+ followup #11 in PR #3's body
- Current `orphan_sweeper`: `server/app/workers/tasks.py:250-270`
- Existing tests: `server/tests/test_orphan_sweeper.py`
- `RunStatus` enum: `server/app/models/run.py:11-15`
- `Settings.orphan_threshold_seconds` (existing): `server/app/config.py`
