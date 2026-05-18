# `orphan_sweeper` QUEUED Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `orphan_sweeper` to mark stuck-QUEUED runs FAILED with `error_summary="never_picked_up"` once `created_at` exceeds a new `queued_threshold_seconds` setting (default 30 min).

**Architecture:** Add one new `Settings` field, then add a second `UPDATE` statement in the existing `orphan_sweeper` cron — two queries, one transaction. The two UPDATEs use distinct `error_summary` values so operators can distinguish "worker died mid-run" from "worker never started job."

**Tech Stack:** Python 3.13, SQLAlchemy 2.0 async, Pydantic-settings, pytest-asyncio. Worker = arq cron. DB layer = aiosqlite in test, asyncpg in dev/prod.

**Spec:** `docs/superpowers/specs/2026-05-18-orphan-sweep-queued-design.md` (committed `0011f8c`).

---

## File map

| File | Change | Reason |
|------|--------|--------|
| `server/app/config.py` | Add 1 field to `Settings` | Operator-tunable threshold |
| `server/tests/test_orphan_sweeper.py` | Add 2 new tests | RED step — defines expected behavior |
| `server/app/workers/tasks.py` | Modify `orphan_sweeper` (lines 250-270) | GREEN step — second UPDATE for QUEUED |

No new files. No migration. No schema change. No frontend.

---

## Task 1: Add `queued_threshold_seconds` Settings field

**Files:**
- Modify: `server/app/config.py:19`

The setting sits in the Wave 2 block alongside the existing `orphan_threshold_seconds`. 30 minutes default tolerates a backlog of ~2-3 queued runs of 5-15 min each before false-positive-ing — see spec §3.

- [ ] **Step 1: Add the new field**

Edit `server/app/config.py`. After line 19 (the existing `orphan_threshold_seconds` field), add one line so the Wave 2 block reads:

```python
    redis_url: str = "redis://localhost:6379/0"
    heartbeat_interval_seconds: int = 30
    orphan_threshold_seconds: int = 600  # 10 minutes
    queued_threshold_seconds: int = 1800  # 30 minutes — stuck QUEUED → FAILED
    default_llm_provider: str = "openai"
```

- [ ] **Step 2: Verify the module still imports**

Run from project root:

```bash
cd server && uv run python -c "from app.config import get_settings; s = get_settings(); print('queued_threshold_seconds =', s.queued_threshold_seconds)"
```

Expected output:
```
queued_threshold_seconds = 1800
```

If this fails with a Pydantic validation error, the most likely cause is a typo or misplaced indent — re-read the file and fix.

- [ ] **Step 3: Commit**

```bash
git add server/app/config.py
git commit -m "$(cat <<'EOF'
feat(server): add queued_threshold_seconds setting (default 30 min)

New Settings field used by orphan_sweeper to mark stuck-QUEUED runs
FAILED. Default 1800s tolerates a backlog of 2-3 queued runs of
5-15 min each. Operator-tunable via env var.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Write failing tests for QUEUED sweep (RED)

**Files:**
- Modify: `server/tests/test_orphan_sweeper.py` (append 2 new tests)

Reuse the existing `_wrapper_factory` helper at the top of the file (lines 12-23) and the existing `monkeypatch.setattr(worker_tasks, "_session_factory_for_worker", _wrapper_factory(db_session))` pattern. Use distinct `github_id` values (`gh-osq1`, `gh-osq2`) — the User table has a unique constraint and tests share `db_session` rollback state.

The first test exercises the new code path; the second guards against false positives on a legitimate backlog. Both tests assert that `last_heartbeat_at` stays NULL — QUEUED runs never had a heartbeat, and the new code must not touch it.

- [ ] **Step 1: Append the first new test**

Open `server/tests/test_orphan_sweeper.py`. After the existing `test_orphan_sweeper_ignores_terminal_runs` function (ending at line 80), append:

```python


@pytest.mark.asyncio
async def test_orphan_sweeper_marks_stale_queued_as_failed(db_session, monkeypatch):
    """Spec §4: a QUEUED run whose created_at is older than
    queued_threshold_seconds must be marked FAILED with
    error_summary='never_picked_up'. last_heartbeat_at stays NULL."""
    monkeypatch.setattr(worker_tasks, "_session_factory_for_worker",
                        _wrapper_factory(db_session))
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-osq1"))
    now = datetime.now(timezone.utc)
    stale_id = uuid.uuid4()
    db_session.add(
        Run(
            id=stale_id, user_id=uid, ticker="NVDA", trade_date="2024-05-10",
            status=RunStatus.QUEUED, results_path="x",
            created_at=now - timedelta(hours=1),
            # last_heartbeat_at intentionally NULL — QUEUED runs never heartbeat.
        )
    )
    await db_session.flush()

    await worker_tasks.orphan_sweeper({"redis": None})
    await db_session.flush()
    stale = (await db_session.execute(select(Run).where(Run.id == stale_id))).scalar_one()
    assert stale.status is RunStatus.FAILED
    assert stale.error_summary == "never_picked_up"
    assert stale.completed_at is not None
    assert stale.last_heartbeat_at is None
```

- [ ] **Step 2: Append the second new test**

Below the function added in Step 1, append:

```python


@pytest.mark.asyncio
async def test_orphan_sweeper_ignores_fresh_queued(db_session, monkeypatch):
    """A QUEUED run whose created_at is within the threshold window must
    stay QUEUED — false-positives would penalize legitimate backlog runs."""
    monkeypatch.setattr(worker_tasks, "_session_factory_for_worker",
                        _wrapper_factory(db_session))
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-osq2"))
    now = datetime.now(timezone.utc)
    fresh_id = uuid.uuid4()
    db_session.add(
        Run(
            id=fresh_id, user_id=uid, ticker="AAPL", trade_date="2024-05-10",
            status=RunStatus.QUEUED, results_path="x",
            created_at=now - timedelta(seconds=60),
        )
    )
    await db_session.flush()

    await worker_tasks.orphan_sweeper({"redis": None})
    await db_session.flush()
    fresh = (await db_session.execute(select(Run).where(Run.id == fresh_id))).scalar_one()
    assert fresh.status is RunStatus.QUEUED
    assert fresh.error_summary is None
    assert fresh.completed_at is None
```

- [ ] **Step 3: Run the new tests and verify they FAIL**

```bash
cd server && uv run pytest tests/test_orphan_sweeper.py -v
```

Expected:
- `test_orphan_sweeper_marks_stale_running_as_failed` PASSES (untouched)
- `test_orphan_sweeper_ignores_terminal_runs` PASSES (untouched)
- `test_orphan_sweeper_marks_stale_queued_as_failed` **FAILS** with `AssertionError: ... RunStatus.QUEUED is not RunStatus.FAILED` (the sweeper currently ignores QUEUED entirely)
- `test_orphan_sweeper_ignores_fresh_queued` PASSES vacuously (sweeper doesn't touch QUEUED yet, so the assertion that it stays QUEUED is true for the wrong reason — that's fine; it becomes meaningful after Task 3)

If the stale-queued test PASSES, something is wrong — either the sweeper is already implementing this behavior, or the test isn't actually inserting the row. Stop and investigate.

- [ ] **Step 4: Commit the failing test**

```bash
git add server/tests/test_orphan_sweeper.py
git commit -m "$(cat <<'EOF'
test(server): failing tests for orphan_sweeper QUEUED sweep

Two new tests — stale-QUEUED→FAILED and fresh-QUEUED→stays-QUEUED.
Stale test currently fails (sweeper ignores QUEUED entirely);
fresh test passes vacuously and becomes meaningful after the
implementation lands in the next commit.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Implement QUEUED sweep (GREEN)

**Files:**
- Modify: `server/app/workers/tasks.py:250-270`

Replace the existing `orphan_sweeper` function with a version that runs two UPDATEs in one transaction. Keep the existing RUNNING branch verbatim except for factoring `now` and `running_threshold` out so the QUEUED branch can share them. Distinguish the two failure modes via `error_summary` so operators can triage.

- [ ] **Step 1: Replace `orphan_sweeper`**

Open `server/app/workers/tasks.py`. Replace lines 250-270 (the entire `async def orphan_sweeper` function) with:

```python
async def orphan_sweeper(ctx: dict) -> None:
    """Cron: mark stale RUNNING + stale QUEUED rows as failed.

    Two parallel sweeps, one transaction:
    - RUNNING: heartbeat older than orphan_threshold_seconds → worker
      died mid-run. Marked FAILED with error_summary='worker_lost'.
    - QUEUED:  created_at older than queued_threshold_seconds → worker
      never picked it up. Marked FAILED with error_summary='never_picked_up'.

    The two summaries are distinguishable so operators can triage:
    'worker_lost' points at process/OOM/segfault investigation;
    'never_picked_up' points at arq/Redis/worker-registration.
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
            running_result.rowcount,
            queued_result.rowcount,
        )
```

- [ ] **Step 2: Run the orphan_sweeper tests and verify all 4 PASS**

```bash
cd server && uv run pytest tests/test_orphan_sweeper.py -v
```

Expected: 4 passed, 0 failed.

If the stale-queued test still fails, check that the new `.where(Run.status == RunStatus.QUEUED, Run.created_at < queued_threshold)` clause references `Run.created_at` (not `Run.last_heartbeat_at` — that column is NULL for QUEUED rows and the comparison would always be False).

If the stale-running test (`test_orphan_sweeper_marks_stale_running_as_failed`) fails, you accidentally broke the existing branch. Re-read the diff against the pre-change function and restore the WHERE clause exactly.

- [ ] **Step 3: Run the full server test suite to catch unrelated regressions**

```bash
cd server && uv run pytest -q
```

Expected: all tests pass. The baseline before this change was 144 tests (per spec §8.2); this change adds 2, so expect 146 passed. A baseline of N≠144 is fine as long as `N + 2` pass after this change — the spec count is informational, not load-bearing.

If any unrelated test fails, do not proceed — investigate. The most likely cause is an import-time side effect from the new Settings field, but that shouldn't happen because Pydantic-settings supplies the default.

- [ ] **Step 4: Verify the log line includes both counts**

```bash
cd server && grep -n "stuck-running.*stuck-queued" app/workers/tasks.py
```

Expected: one match, on the `logger.info(...)` line inside `orphan_sweeper`.

This is a quick sanity check that the log message wasn't accidentally left in its old single-count form.

- [ ] **Step 5: Commit**

```bash
git add server/app/workers/tasks.py
git commit -m "$(cat <<'EOF'
feat(server): orphan_sweeper marks stuck-QUEUED runs as never_picked_up

Second UPDATE in the same transaction marks Run.status==QUEUED rows
whose created_at is older than queued_threshold_seconds as FAILED
with error_summary='never_picked_up'. Distinct from the existing
'worker_lost' marker so operators can triage which failure mode hit.

Catches the case where the worker crashed before pickup or the arq
queue lost the job. Race with run_propagate is pre-existing and
documented out-of-scope in spec §7.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Final verification & PR readiness check

**Files:** none modified — read-only verification.

- [ ] **Step 1: Verify the branch diff matches the spec's promised file list**

```bash
git diff main..HEAD --name-only
```

Expected output (exactly 4 files):
```
docs/superpowers/plans/2026-05-18-orphan-sweep-queued.md
docs/superpowers/specs/2026-05-18-orphan-sweep-queued-design.md
server/app/config.py
server/app/workers/tasks.py
server/tests/test_orphan_sweeper.py
```

Wait — that's 5, not 4. The spec §8.4 said 4 but did not count the plan doc itself. 5 is the correct expected count once the plan is also in-tree. If any OTHER file appears, stop and investigate (it likely means a working-tree contamination snuck in via `git add .` — never use that; always `git add <exact path>`).

- [ ] **Step 2: Verify commit count**

```bash
git log main..HEAD --oneline
```

Expected: 4 commits (spec + plan? — the plan was added before this skill ran; check if it's already committed; if not, commit it separately first), plus config + tests + tasks. Total 4 if plan was committed during writing-plans, otherwise 5 if you commit the plan at the end.

If the plan file is uncommitted at this point, commit it now:

```bash
git add docs/superpowers/plans/2026-05-18-orphan-sweep-queued.md
git commit -m "plan: orphan_sweeper QUEUED sweep — 3 tasks, TDD, atomic commits"
```

- [ ] **Step 3: Final test run**

```bash
cd server && uv run pytest tests/test_orphan_sweeper.py -v && uv run pytest -q
```

Both invocations must show all-green.

- [ ] **Step 4: Confirm spec verification gates (spec §8) are all true**

Walk through spec §8's 6 gates:

1. `cd server && uv run pytest tests/test_orphan_sweeper.py -v` → 4 tests passing ✅
2. `cd server && uv run pytest -q` → 144 baseline + 2 new pass ✅
3. `grep -c "never_picked_up\|queued_threshold_seconds" server/app/workers/tasks.py server/app/config.py` → ≥3
4. `git diff main..HEAD --name-only` → spec + plan + config + tasks + test_orphan_sweeper (5 files; spec §8.4 said 4 because it didn't count the plan — see Step 1 note)
5. Log line mentions both `stuck-running` and `stuck-queued` ✅ (verified in Task 3 Step 4)
6. Existing 2 orphan_sweeper tests still pass without modification ✅ (verified in Task 3 Step 2)

Run gate 3 explicitly:

```bash
grep -c "never_picked_up\|queued_threshold_seconds" server/app/workers/tasks.py server/app/config.py
```

Expected: `server/app/workers/tasks.py:2` (one mention of `queued_threshold_seconds`, one of `never_picked_up`) and `server/app/config.py:1` — total ≥3.

- [ ] **Step 5: Push and open PR**

```bash
git push -u origin feature/orphan-sweep-queued
gh pr create --title "feat(server): orphan_sweeper sweeps stuck-QUEUED runs" --body "$(cat <<'EOF'
## Summary

- Adds `Settings.queued_threshold_seconds` (default 30 min — see spec §3 for tuning rationale)
- Adds a second `UPDATE` inside `orphan_sweeper` that marks `Run.status==QUEUED AND created_at<threshold` as `FAILED` with `error_summary="never_picked_up"`
- Two queries, one transaction. Distinguishable from the existing `worker_lost` failure mode for operator triage

## Spec

`docs/superpowers/specs/2026-05-18-orphan-sweep-queued-design.md`

## Out-of-scope (documented in spec §2)

- Fixing the pre-existing race in `run_propagate` (worker doesn't check current status before setting RUNNING). Separate followup.
- Index on `Run.created_at` — current single-table-scan + status filter is fine on dev DB sizes.
- Different UI treatment for the two failure modes. Frontend renders both as "Failed" with `error_summary` in detail view.

## Test plan

- [x] `cd server && uv run pytest tests/test_orphan_sweeper.py -v` → 4 passed
- [x] `cd server && uv run pytest -q` → all green (baseline + 2 new)
- [x] Log line mentions both `stuck-running` and `stuck-queued` counts

## v3+ followup

Closes v3+ #11 from PR #3 body.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Return the PR URL on completion.

---

## Done when

- All 4 orphan_sweeper tests pass.
- Full `pytest -q` is green.
- 4 commits on branch (config, tests, tasks; plan committed separately at writing-plans time).
- PR opened against `main`.
- Spec §8's 6 verification gates all true.
