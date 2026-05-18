# OpenAPI-TypeScript Codegen (Portfolio Types) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 7 hand-mirrored portfolio types in `web/lib/types.ts` with codegen output derived from FastAPI's `app.openapi()`. Closes v3+ followup #12.

**Architecture:** Two-stage pipeline. Stage 1: a small Python module (`server/app/export_openapi.py`) calls `app.openapi()` and writes the JSON to stdout. Stage 2: `npx openapi-typescript` reads that JSON and produces `web/lib/openapi-types.ts`. Both stages are wired into a single `npm run codegen` script in `web/package.json`. The generated `.ts` file is committed; `openapi.json` is gitignored. `web/lib/types.ts` is rewritten to re-export the 7 portfolio types from the generated file using friendly names, so the 10 existing consumer imports (`import type { DecisionPin } from "@/lib/types"`) stay unchanged. A second script `npm run codegen:check` regenerates to `/tmp`, diffs against the committed file, and fails on drift.

**Tech Stack:** Python 3.10+, FastAPI 0.118+, uv, Node.js 20+, npm, TypeScript 5.6+, openapi-typescript v7.

**Spec:** `docs/superpowers/specs/2026-05-18-openapi-typescript-codegen-design.md`

---

## File Structure

| File | Status | Responsibility |
|------|--------|----------------|
| `server/app/export_openapi.py` | CREATE | ~22 lines: `app.openapi()` → JSON to stdout, with env-setdefault for import-time safety. |
| `server/openapi.json` | GITIGNORED | Intermediate artifact, never committed. |
| `web/lib/openapi-types.ts` | CREATE (generated) | Codegen output. Committed. Devs do NOT hand-edit. |
| `web/lib/types.ts` | MODIFY | 7 portfolio types become `type X = components["schemas"]["X"]` re-exports. Other 10 types unchanged. |
| `web/package.json` | MODIFY | Add `openapi-typescript` to devDependencies; add `codegen` + `codegen:check` scripts. |
| `web/package-lock.json` | UPDATE | npm-managed; reflects new dep. |
| `.gitignore` | MODIFY | Add `server/openapi.json` entry. |

No router changes. No Pydantic schema changes. No test file changes. No consumer file changes (the wrapper preserves all 10 import sites).

---

## Task 1: Server export script + manual verification

**Files:**
- Create: `server/app/export_openapi.py`
- Modify: `.gitignore` (root)

This task creates the Python script that emits the OpenAPI JSON. No npm work yet — pure server side.

- [ ] **Step 1: Add `server/openapi.json` to the root `.gitignore`**

Open `/Users/erikgunawansupriatna/TradingAgents/.gitignore` and append (at the end of the file, with a blank line above for clarity):

```
# OpenAPI codegen intermediate (web/lib/openapi-types.ts is the committed output).
server/openapi.json
```

- [ ] **Step 2: Create `server/app/export_openapi.py`** with exact content:

```python
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
os.environ.setdefault("DASHBOARD_DATA_DIR", "/tmp/codegen-placeholder")

from app.main import app  # noqa: E402 — imports MUST follow env setdefault


def main() -> None:
    print(json.dumps(app.openapi(), indent=2))


if __name__ == "__main__":
    main()
```

The `# noqa: E402` is required because ruff flags "module level import not at top of file"; the env setdefault must precede `app.main` import or settings validation fails. The noqa is intentional and load-bearing.

- [ ] **Step 3: Verify the script runs and produces valid JSON containing the portfolio schemas**

From the project root:

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run python -m app.export_openapi 2>&1 | head -3
```

Expected: first line is `{`, the next two lines are JSON keys (likely `"openapi"` and `"info"`). NO Python tracebacks. If you see `ImportError`, `ValidationError` from settings, or any Python exception, STOP and report.

- [ ] **Step 4: Verify the JSON contains the expected portfolio schemas**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run python -m app.export_openapi 2>/dev/null | python3 -c "
import json, sys
doc = json.load(sys.stdin)
schemas = doc.get('components', {}).get('schemas', {})
required = ['DecisionPin', 'PortfolioSummaryOut', 'PortfolioCurveOut', 'PricePoint', 'PnLPoint', 'TickerDetailOut', 'MemoryEntryStatus']
missing = [s for s in required if s not in schemas]
print(f'present: {sorted([s for s in required if s in schemas])}')
print(f'missing: {sorted(missing)}')
assert not missing, f'Missing schemas: {missing}'
print('PASS')
"
```

Expected output:

```
present: ['DecisionPin', 'MemoryEntryStatus', 'PnLPoint', 'PortfolioCurveOut', 'PortfolioSummaryOut', 'PricePoint', 'TickerDetailOut']
missing: []
PASS
```

If `missing` is non-empty, the codegen will produce broken `openapi-types.ts`. STOP and investigate — likely cause is a Pydantic schema that's defined but not referenced by any route's `response_model=` or request body.

- [ ] **Step 5: Lint pass**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run ruff check app/export_openapi.py
```

Expected: `All checks passed!`. The `# noqa: E402` suppresses the import-order check; no other warnings should fire.

- [ ] **Step 6: Verify no test regression**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest -q 2>&1 | tail -3
```

Expected: 144 passed (the post-PR-#5-merge baseline). The new file is not imported by any test — should have zero effect.

- [ ] **Step 7: Commit**

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git add server/app/export_openapi.py .gitignore
git commit -m "$(cat <<'EOF'
feat(server): export_openapi script for openapi-typescript codegen

Pure introspection over registered routes + Pydantic schemas. Used
by `web/npm run codegen` (next task) to produce TypeScript types
without requiring the server to be running.

Env setdefault mirrors tests/conftest.py so app.main is importable
without a real .env. The values are never used at runtime —
the script doesn't open DB connections or verify JWTs.

server/openapi.json (intermediate artifact) added to .gitignore;
the committed artifact is web/lib/openapi-types.ts (next task).

Implements spec §5 of v3+ followup #12.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Web codegen setup + first generation

**Files:**
- Modify: `web/package.json`
- Update: `web/package-lock.json` (npm-managed)
- Create: `web/lib/openapi-types.ts` (generated, committed)

- [ ] **Step 1: Add `openapi-typescript` to devDependencies and the two scripts**

Open `/Users/erikgunawansupriatna/TradingAgents/web/package.json`. The current `"scripts"` block:

```json
"scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "typecheck": "tsc --noEmit",
    "test:e2e": "playwright test"
}
```

Replace with:

```json
"scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "typecheck": "tsc --noEmit",
    "test:e2e": "playwright test",
    "codegen": "uv --directory ../server run python -m app.export_openapi > ../server/openapi.json && npx openapi-typescript ../server/openapi.json -o lib/openapi-types.ts",
    "codegen:check": "uv --directory ../server run python -m app.export_openapi > /tmp/openapi-check.json && npx openapi-typescript /tmp/openapi-check.json -o /tmp/openapi-types-check.ts && diff lib/openapi-types.ts /tmp/openapi-types-check.ts && rm -f /tmp/openapi-check.json /tmp/openapi-types-check.ts"
}
```

(The `--directory ../server` is uv's way of running in another directory. The trailing `rm -f` only fires on diff success — see spec §7. On diff failure, the temp files leak to `/tmp` and get cleaned by the OS; surfacing the drift is more important than perfect cleanup.)

In the same file, add `"openapi-typescript": "^7.4.0"` to `devDependencies`:

```json
"devDependencies": {
    "@playwright/test": "^1.49.0",
    "@types/node": "^22.0.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "openapi-typescript": "^7.4.0",
    "typescript": "^5.6.0"
}
```

(Alphabetical sort within devDependencies — keep the file tidy.)

- [ ] **Step 2: Install the new dep**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/web && npm install
```

Expected: no errors. `package-lock.json` updates with `openapi-typescript` and its transitive deps. May take 10-30 seconds depending on cache state.

- [ ] **Step 3: Run codegen to produce the generated file**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/web && npm run codegen
```

Expected: no errors. Two artifacts produced:
- `/Users/erikgunawansupriatna/TradingAgents/server/openapi.json` (gitignored — intermediate)
- `/Users/erikgunawansupriatna/TradingAgents/web/lib/openapi-types.ts` (committed — generated)

Common failure: `Could not find module app.main` → server/.venv isn't set up (`uv sync`). Run `cd ../server && uv sync` then retry.

- [ ] **Step 4: Verify the generated file has the expected schemas**

```bash
grep -c "DecisionPin\|PortfolioSummaryOut\|PortfolioCurveOut\|PricePoint\|PnLPoint\|TickerDetailOut\|MemoryEntryStatus" /Users/erikgunawansupriatna/TradingAgents/web/lib/openapi-types.ts
```

Expected: a count of at least 7 (each schema name appears at least once as a key under `components.schemas`, plus more as references inside other schemas).

- [ ] **Step 5: Verify the generated file is valid TypeScript**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/web && npx tsc --noEmit lib/openapi-types.ts 2>&1 | head -10
```

Expected: no output (success), OR errors about JSX/React if `tsc` config is too narrow — in which case the next step's full `npm run typecheck` is the real check. If the file has internal contradictions, you'll see actual TS errors. STOP if you see them; investigate.

- [ ] **Step 6: Spot-check the generated DecisionPin shape**

```bash
grep -A 10 "DecisionPin:" /Users/erikgunawansupriatna/TradingAgents/web/lib/openapi-types.ts | head -15
```

Expected output (or close to it — openapi-typescript v7 formatting may vary slightly):

```
        DecisionPin: {
            trade_date: string;
            rating: string;
            status: components["schemas"]["MemoryEntryStatus"];
            raw_return: number | null;
        };
```

Key checks:
- `status` references `components["schemas"]["MemoryEntryStatus"]` (because PR #7 made `status` use the `$ref` form)
- `raw_return: number | null` (Pydantic `float | None` → TS `number | null`)
- All 4 fields present, no extras

If the shape is wildly different (e.g., status is a string literal, raw_return is required), the codegen tool's interpretation differs from expectation — investigate before continuing.

- [ ] **Step 7: Verify codegen output is deterministic (run it twice, expect no diff)**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/web && cp lib/openapi-types.ts /tmp/codegen-baseline.ts && npm run codegen && diff /tmp/codegen-baseline.ts lib/openapi-types.ts && echo "DETERMINISTIC: identical output on second run" && rm /tmp/codegen-baseline.ts
```

Expected: prints "DETERMINISTIC: identical output on second run" with no diff output. If diff is non-empty, the tool produces non-deterministic output (timestamps, ordering) — the `codegen:check` script (Task 4) won't work. STOP and investigate.

- [ ] **Step 8: Commit**

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git add web/package.json web/package-lock.json web/lib/openapi-types.ts
git commit -m "$(cat <<'EOF'
feat(web): openapi-typescript codegen — generated types + npm scripts

Adds openapi-typescript v7 as a dev dep. Two npm scripts:
- `npm run codegen` — regenerates lib/openapi-types.ts from
  server's app.openapi() output
- `npm run codegen:check` — drift detection (regenerates to /tmp,
  diffs against committed, fails non-zero on drift)

The generated lib/openapi-types.ts is committed (~150 lines of
type definitions covering all FastAPI routes + schemas reachable
from a response_model). Devs do NOT hand-edit it — re-run codegen
after Pydantic schema changes.

Consumer migration (web/lib/types.ts re-exports) is next task.

Implements spec §4 + §7 of v3+ followup #12.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Wrapper rewrite — `web/lib/types.ts` re-exports

**Files:**
- Modify: `web/lib/types.ts`

This task swaps the 7 hand-defined portfolio types to re-exports from `openapi-types.ts`. The 10 remaining hand-defined types (runs, user, launch) stay as-is.

- [ ] **Step 1: Read the current `web/lib/types.ts` carefully** to confirm the 7 portfolio types and their positions

```bash
grep -n "^export" /Users/erikgunawansupriatna/TradingAgents/web/lib/types.ts
```

Expected output (or close):

```
1:export type RunStatus = "queued" | "running" | "succeeded" | "failed";
3:export interface RunOut {
13:export interface RunListOut {
17:export interface ReportSections {
27:export interface RunDetailOut extends RunOut {
33:export interface UserOut {
40:export type AnalystKey = "market" | "social" | "news" | "fundamentals";
42:export interface RunCreate {
49:export interface RunTailOut {
57:export type MemoryEntryStatus = "pending" | "resolved";
59:export interface PortfolioSummaryOut {
68:export interface PnLPoint {
73:export interface PortfolioCurveOut {
77:export interface PricePoint {
82:export interface DecisionPin {
89:export interface TickerDetailOut {
```

The portfolio types start at line 55 (the `--- Wave 3: portfolio ---` comment) and run through end of file. Lines 1-53 are the non-portfolio types (preserved unchanged).

- [ ] **Step 2: Replace the portfolio section (lines 55 to end) with re-exports**

Edit `/Users/erikgunawansupriatna/TradingAgents/web/lib/types.ts`. Find this block (currently lines 55-93 — the entire portfolio section):

```typescript
// --- Wave 3: portfolio ---

export type MemoryEntryStatus = "pending" | "resolved";

export interface PortfolioSummaryOut {
  trade_count: number;
  win_rate: number;
  sharpe: number;
  max_drawdown: number;
  /** Sum of per-decision P&L; same units as PnLPoint.cumulative_pnl. */
  cumulative_pnl: number;
}

export interface PnLPoint {
  trade_date: string;
  cumulative_pnl: number;
}

export interface PortfolioCurveOut {
  points: PnLPoint[];
}

export interface PricePoint {
  trade_date: string;
  close: number;
}

export interface DecisionPin {
  trade_date: string;
  rating: string;
  status: MemoryEntryStatus;
  raw_return: number | null;
}

export interface TickerDetailOut {
  ticker: string;
  prices: PricePoint[];
  decisions: DecisionPin[];
}
```

Replace with TWO edits in the same file:

**Edit A:** Insert at the very top of `web/lib/types.ts` (before line 1's `export type RunStatus = ...`):

```typescript
import type { components } from "@/lib/openapi-types";

```

(One `import type` line + one blank line. TypeScript requires imports at the top of the file; this is the only correct placement.)

**Edit B:** Replace the entire portfolio section (currently lines ~55-93 — from `// --- Wave 3: portfolio ---` through end of file) with:

```typescript
// --- Wave 3: portfolio — generated from FastAPI Pydantic schemas ---
//
// These 7 types are re-exported from web/lib/openapi-types.ts. Do NOT
// hand-edit them here. After changing a Pydantic schema in
// server/app/schemas/portfolio.py, run `npm run codegen` to regenerate
// the openapi-types.ts file; the re-exports below pick up changes
// automatically. `npm run codegen:check` fails if the committed
// openapi-types.ts is stale relative to the current Pydantic schemas.
//
// Other types in this file (RunStatus, RunOut, etc.) remain
// hand-defined until their Pydantic counterparts are migrated.
// The `components` import is at the top of the file (line 1).

export type MemoryEntryStatus = components["schemas"]["MemoryEntryStatus"];
export type PortfolioSummaryOut = components["schemas"]["PortfolioSummaryOut"];
export type PnLPoint = components["schemas"]["PnLPoint"];
export type PortfolioCurveOut = components["schemas"]["PortfolioCurveOut"];
export type PricePoint = components["schemas"]["PricePoint"];
export type DecisionPin = components["schemas"]["DecisionPin"];
export type TickerDetailOut = components["schemas"]["TickerDetailOut"];
```

After Edits A+B, the file structure is:
1. Line 1: `import type { components } from "@/lib/openapi-types";`
2. Line 2: blank
3. Lines 3-54: existing hand-defined types (RunStatus, RunOut, ..., RunTailOut) — unchanged
4. Lines 55-end: replaced portfolio section (comment block + 7 re-export lines)

- [ ] **Step 3: Verify the file compiles**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/web && npm run typecheck 2>&1 | tail -10
```

Expected: no output, or only "tsc done" / no error lines. If you see `Cannot find module '@/lib/openapi-types'` — the codegen from Task 2 didn't run or didn't write to the expected path. If you see `Property 'X' does not exist on type 'components["schemas"]["Y"]'` — the generated shape differs from what consumers expect; investigate per-consumer.

- [ ] **Step 4: Verify all 10 consumer files still type-check correctly**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/web && npm run typecheck 2>&1 | grep -E "(\.tsx|\.ts):" | head -20
```

Expected: empty output (no errors). If you see errors in `components/PortfolioStats.tsx`, `components/PnLChart.tsx`, `components/DecisionTimeline.tsx`, `components/TickerPriceChart.tsx`, `app/portfolio/[ticker]/page.tsx`, OR `lib/api.ts`, the re-exported types have a different shape than the hand-mirrored versions did. STOP and investigate per error.

- [ ] **Step 5: Verify the file is clean (no stray content)**

```bash
wc -l /Users/erikgunawansupriatna/TradingAgents/web/lib/types.ts
```

Expected: line count should DROP from 94 to roughly 60-65 (lost the inline portfolio definitions, gained the import + comment + 7 re-export lines). If it's much higher or lower, re-inspect.

- [ ] **Step 6: Smoke test — render an existing portfolio page in dev mode**

This step is optional but recommended. If you have time:

```bash
cd /Users/erikgunawansupriatna/TradingAgents/web && timeout 15 npm run dev 2>&1 | head -20
```

Expected: dev server starts, no TypeScript errors on startup. Kill it after seeing it boot (Ctrl+C). The point is to confirm the build pipeline accepts the new types — full E2E is out of scope.

- [ ] **Step 7: Commit**

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git add web/lib/types.ts
git commit -m "$(cat <<'EOF'
refactor(web): re-export portfolio types from generated openapi-types

The 7 portfolio types (MemoryEntryStatus, PortfolioSummaryOut, PnLPoint,
PortfolioCurveOut, PricePoint, DecisionPin, TickerDetailOut) are now
re-exports from lib/openapi-types.ts (generated by `npm run codegen`).

All 10 consumer files keep their existing
`import type { DecisionPin } from "@/lib/types"` imports unchanged.
The wrapper pattern means the friendly names (DecisionPin) hide
openapi-typescript's bracket-access output
(components["schemas"]["DecisionPin"]).

Other types (RunStatus, RunOut, UserOut, AnalystKey, RunCreate,
RunTailOut, ReportSections, RunDetailOut, RunListOut) remain
hand-defined for now. Migrate incrementally as their Pydantic
counterparts evolve.

Implements spec §6 of v3+ followup #12.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Drift-check smoke test + commit

**Files:** None modified. This task only verifies that `npm run codegen:check` works correctly.

- [ ] **Step 1: Baseline check — should pass immediately**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/web && npm run codegen:check
```

Expected: no diff output, no error. If diff is non-empty, the committed file is already stale — re-run `npm run codegen` and recommit.

- [ ] **Step 2: Smoke-test drift detection — induce a fake schema change and verify drift-check fails**

Make a temporary, harmless change to a Pydantic schema. Open `/Users/erikgunawansupriatna/TradingAgents/server/app/schemas/portfolio.py`. Find the `PnLPoint` class:

```python
class PnLPoint(BaseModel):
    trade_date: str
    cumulative_pnl: float
```

Add a temporary field:

```python
class PnLPoint(BaseModel):
    trade_date: str
    cumulative_pnl: float
    test_drift_marker: str | None = None  # TEMPORARY — remove after Task 4 step 4
```

- [ ] **Step 3: Run drift-check — expect failure**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/web && npm run codegen:check 2>&1 | tail -10
```

Expected: diff output showing `+ test_drift_marker?: string | null;` (or similar) in the PnLPoint schema, followed by a non-zero exit code. The drift-check script's `diff lib/openapi-types.ts /tmp/openapi-types-check.ts` returns non-zero when files differ, and `npm` reports the script as failed.

If the script reports success despite the temporary field, the drift-check is broken — STOP and investigate. Common cause: the script's `>` redirection is buffering, or the `&&` chain is mis-parsed by the shell.

- [ ] **Step 4: Revert the temporary field and re-verify drift-check passes**

Remove the `test_drift_marker: str | None = None` line from `server/app/schemas/portfolio.py`. The file should be back to its pre-Task-4 state.

```bash
cd /Users/erikgunawansupriatna/TradingAgents/web && npm run codegen:check
```

Expected: no output, no error. Drift-check passes again. If it still fails, the schema file wasn't fully reverted.

- [ ] **Step 5: Confirm nothing was committed during the smoke test**

```bash
cd /Users/erikgunawansupriatna/TradingAgents && git status --short server/app/schemas/portfolio.py web/lib/openapi-types.ts
```

Expected: empty output. The smoke test was purely verification; the temporary field was reverted; no permanent change should remain.

- [ ] **Step 6: No commit needed for Task 4**

This task is verification-only; nothing was changed permanently. Move to the final verification.

---

## Verification (final goal-backward check)

Before declaring done, an engineer (or `gsd-verifier` subagent) confirms each gate:

- [ ] **V1 — Server export script works.** `cd /Users/erikgunawansupriatna/TradingAgents/server && uv run python -m app.export_openapi 2>/dev/null | head -1` outputs `{` (valid JSON start, no traceback).
- [ ] **V2 — All 7 portfolio schemas present.** `cd /Users/erikgunawansupriatna/TradingAgents/server && uv run python -m app.export_openapi 2>/dev/null | python3 -c "import json,sys; s=json.load(sys.stdin)['components']['schemas']; assert all(k in s for k in ['DecisionPin','PortfolioSummaryOut','PortfolioCurveOut','PricePoint','PnLPoint','TickerDetailOut','MemoryEntryStatus']); print('PASS')"` prints `PASS`.
- [ ] **V3 — npm codegen succeeds.** `cd /Users/erikgunawansupriatna/TradingAgents/web && npm run codegen` exits 0; `web/lib/openapi-types.ts` exists and is non-empty.
- [ ] **V4 — npm codegen:check passes after codegen.** Immediately after V3, `cd /Users/erikgunawansupriatna/TradingAgents/web && npm run codegen:check` exits 0 with no output.
- [ ] **V5 — TypeScript compiles.** `cd /Users/erikgunawansupriatna/TradingAgents/web && npm run typecheck` exits 0 with no errors.
- [ ] **V6 — Re-exports in place.** `grep -c "components\[" /Users/erikgunawansupriatna/TradingAgents/web/lib/types.ts` returns at least 7 (one re-export line per portfolio type).
- [ ] **V7 — Inline portfolio types removed.** `grep -c "^export interface DecisionPin\|^export interface PortfolioSummaryOut\|^export interface PnLPoint\|^export interface PortfolioCurveOut\|^export interface PricePoint\|^export interface TickerDetailOut\|^export type MemoryEntryStatus = \"pending\"" /Users/erikgunawansupriatna/TradingAgents/web/lib/types.ts` returns 0 (none of the old hand-defined exports remain).
- [ ] **V8 — Consumer imports unchanged.** `git diff main..HEAD --name-only -- web/components/ web/app/ web/lib/api.ts` is empty (zero diff to consumers).
- [ ] **V9 — Tests + ruff still pass.** `cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest -q && uv run ruff check app/export_openapi.py` shows 144 tests pass + ruff clean.
- [ ] **V10 — Gitignore covers openapi.json.** `grep -c "openapi.json" /Users/erikgunawansupriatna/TradingAgents/.gitignore` returns at least 1.
- [ ] **V11 — Spec sections covered:**
  - §3 architecture (two-stage pipeline) → Tasks 1+2
  - §5 export script → Task 1
  - §6 re-export wrapper → Task 3
  - §7 npm scripts → Task 2 Step 1
  - §8 gitignore → Task 1 Step 1
  - §10 verification → V1-V10 mirror this

If V1-V11 all pass, the implementation is done.

---

## Out-of-scope reminders

These are deliberately NOT done by this plan (per spec §2):

- Migration of non-portfolio types (runs, user, launch) — future per-domain followups.
- Client-side fetch codegen (orval, openapi-fetch). `web/lib/api.ts` stays as-is.
- CI integration (no `.github/workflows/` exists yet).
- Drop the friendly-name wrapper (would require touching 10 consumer files).
- Snapshot test for OpenAPI shape changes (no test infra for this on the web side; pytest doesn't load OpenAPI).

If discovered during implementation, file as new followups — do not bundle.
