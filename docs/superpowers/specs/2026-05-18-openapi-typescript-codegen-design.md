# OpenAPI-TypeScript Codegen (Portfolio Types) — Design

**Status:** Approved, awaiting implementation plan
**Date:** 2026-05-18
**Followup of:** PR #3 (Wave 3 — Portfolio P&L); v3+ followup #12 in the deferred list
**Independent of:** All in-flight work; main currently at `805b9db` (post-PR-#4/#5/#6/#7 merge).
**Author:** erik

---

## 1. Problem

`web/lib/types.ts` (94 lines, 17 type aliases / interfaces) is hand-mirrored from the FastAPI Pydantic schemas. Whenever a Pydantic schema changes — adding a field, renaming a type, changing a literal value — the corresponding TypeScript type silently drifts until someone notices a `tsc` error at the consumer site, OR worse, until a runtime mismatch surfaces in the browser.

Wave 3 (the dashboard) added 7 portfolio types; PRs #6 and #7 (just merged) modified the `DecisionPin` schema (added a validator) and changed the OpenAPI schema shape for `status` (inline `enum` → `$ref` to a named `MemoryEntryStatus` component). The hand-mirrored TS types didn't move. They happen to still be correct because the wire format is unchanged — but that's coincidence, not enforcement.

The v3+ list captured the gap:

> `openapi-typescript` codegen replacing hand-mirrored TS types

This spec replaces the 7 portfolio types with codegen output from FastAPI's auto-generated OpenAPI document. The remaining 10 hand-mirrored types (runs, user, launch) stay as-is; this PR demonstrates the pattern and migrates the most-recently-touched, highest-drift-risk types first.

---

## 2. Goal & non-goals

**Goal.** Make `web/lib/types.ts`'s portfolio types derived (not authored). Adding a field to `DecisionPin` on the server should produce a TypeScript error in the consuming UI on the next `npm run codegen + typecheck` — and a drift-check script (`npm run codegen:check`) prevents forgotten regenerations from silently rotting.

**Non-goals (deliberately).**

- **No client-fetch codegen** (orval, openapi-fetch, etc.). The existing `web/lib/api.ts` (hand-written fetch wrapper) is unchanged. Only **types** are generated; the HTTP transport stays explicit.
- **No migration of non-portfolio types** (runs, user, launch). Those stay hand-mirrored for now. This PR demonstrates the pattern; each subsequent domain can migrate in its own PR when its Pydantic schemas next change.
- **No CI integration.** The repo has no `.github/workflows/` (acknowledged in the lock PR's spec correction). The `codegen:check` script is one line that can be wired into CI when it exists; until then, developers run it manually.
- **No friendly-name strip.** `openapi-typescript` outputs `components["schemas"]["DecisionPin"]`. A wrapper file (`web/lib/types.ts`) re-exports the 7 portfolio types with friendly names so the 10 existing consumer imports (`import type { DecisionPin } from "@/lib/types"`) work unchanged. Dropping the wrapper would force a 10-file consumer migration; rejected as scope creep.
- **No fetch-client refactor**. `web/lib/api.ts` imports a few of these types — its imports continue to work via the re-export wrapper.

---

## 3. Architecture

Two-stage pipeline, both scripts; no service required at codegen time.

```
┌─────────────────────────────┐
│ server/app/export_openapi.py│  (~10 lines)
│  - imports `app.main.app`   │
│  - calls `app.openapi()`    │
│  - writes JSON to stdout    │
└────────────┬────────────────┘
             │  pipe via shell
             ▼
┌─────────────────────────────┐
│  server/openapi.json        │  (gitignored — ephemeral artifact)
└────────────┬────────────────┘
             │  read by openapi-typescript
             ▼
┌─────────────────────────────┐
│  web/lib/openapi-types.ts   │  (generated, COMMITTED — devs don't hand-edit)
│  exports `components`       │
│  with all schemas/operations│
└────────────┬────────────────┘
             │  re-exported with friendly names
             ▼
┌─────────────────────────────┐
│  web/lib/types.ts           │  (MODIFIED — 7 portfolio re-exports +
│                             │   10 remaining hand-defined types unchanged)
└────────────┬────────────────┘
             │
             ▼
   10 consumer files (unchanged imports)
```

**Why static export (not HTTP fetch from a running server):** developer doesn't need to start Docker / uvicorn to regenerate types. Faster, simpler, more portable.

**Why `openapi.json` is gitignored:** it's a machine-generated intermediate. The committed artifact is the TypeScript file (smaller, human-readable diff, frontend devs without Python can review).

---

## 4. Tooling

**`openapi-typescript`** (npm dev dep, latest v7 — currently `7.x`). Maintained by openapi-ts org. Most-used tool of its kind on npm. Generates type-only output (no runtime code). The output shape is:

```typescript
export interface paths { ... }
export interface components {
  schemas: {
    DecisionPin: { trade_date: string; rating: string; status: ...; raw_return: number | null; };
    PortfolioSummaryOut: { ... };
    MemoryEntryStatus: "pending" | "resolved";
    // ...
  };
  // ...
}
```

Consumers access via `components["schemas"]["DecisionPin"]`. The wrapper in `web/lib/types.ts` re-exports with friendly names (see §6).

**`uv`** (already a project dep). Used to invoke the Python export script.

**No client-side tooling change.** Next.js / TypeScript / React Query are not affected.

---

## 5. Schema export script

`server/app/export_openapi.py` (NEW, ~20 lines):

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

from app.main import app  # noqa: E402 — imports after env setdefault


def main() -> None:
    print(json.dumps(app.openapi(), indent=2))


if __name__ == "__main__":
    main()
```

Run from project root: `uv --directory server run python -m app.export_openapi > server/openapi.json`.

(The `web/package.json` script uses `../server/...` paths because npm scripts execute with cwd=`web/`. See §7.)

The `# noqa: E402` is required because ruff flags imports-after-statements; the env-setdefault MUST happen before `app.main` is imported, so the noqa is intentional.

---

## 6. Re-export wrapper

`web/lib/types.ts` is rewritten so the 7 portfolio types are re-exports from the generated file:

```typescript
// Portfolio types — generated from FastAPI Pydantic schemas via
// `npm run codegen`. Do not hand-edit. If the type you need isn't
// here yet, run codegen after adding the field to the Pydantic schema.
import type { components } from "@/lib/openapi-types";

export type MemoryEntryStatus = components["schemas"]["MemoryEntryStatus"];
export type DecisionPin = components["schemas"]["DecisionPin"];
export type PnLPoint = components["schemas"]["PnLPoint"];
export type PortfolioSummaryOut = components["schemas"]["PortfolioSummaryOut"];
export type PortfolioCurveOut = components["schemas"]["PortfolioCurveOut"];
export type PricePoint = components["schemas"]["PricePoint"];
export type TickerDetailOut = components["schemas"]["TickerDetailOut"];

// === The remaining types below are hand-defined until their Pydantic ===
// === counterparts are added/migrated (see v3+ followup notes).      ===

export type RunStatus = "queued" | "running" | "succeeded" | "failed";
// ... rest of file unchanged (RunOut, RunDetailOut, ReportSections,
// UserOut, AnalystKey, RunCreate, RunTailOut, RunListOut)
```

All 10 consumer files (`PortfolioStats.tsx`, `PnLChart.tsx`, `DecisionTimeline.tsx`, etc.) continue to import the same names from the same path. **Zero consumer-file diff.**

---

## 7. NPM scripts

Added to `web/package.json` `"scripts"`:

```json
"codegen": "uv --directory ../server run python -m app.export_openapi > ../server/openapi.json && npx openapi-typescript ../server/openapi.json -o lib/openapi-types.ts",
"codegen:check": "uv --directory ../server run python -m app.export_openapi > /tmp/openapi-check.json && npx openapi-typescript /tmp/openapi-check.json -o /tmp/openapi-types-check.ts && diff lib/openapi-types.ts /tmp/openapi-types-check.ts && rm -f /tmp/openapi-check.json /tmp/openapi-types-check.ts"
```

- **`npm run codegen`**: regenerates `lib/openapi-types.ts` in place. Run after Pydantic schema changes.
- **`npm run codegen:check`**: regenerates to `/tmp`, diffs against the committed file, fails non-zero if different. Cleans up its temp files. Run locally before pushing; will slot into CI when added.

If `diff` reports any difference, the exit code is non-zero and `&&` short-circuits — the cleanup `rm` doesn't run. Acceptable (temp files in `/tmp` get garbage-collected by the OS) and surfaces the drift loudly. A pedantic version would use `trap` to ensure cleanup on failure; not worth the bash complexity here.

---

## 8. Gitignore

`server/.gitignore` (or root `.gitignore` — whichever exists) gets one new line:

```
# Intermediate artifact for OpenAPI codegen (web/lib/openapi-types.ts is the committed output).
openapi.json
```

The `web/lib/openapi-types.ts` file IS committed — it's the source-of-truth derived artifact that frontend reviewers see in PR diffs.

---

## 9. Files touched

| File | Status | Responsibility |
|------|--------|----------------|
| `server/app/export_openapi.py` | CREATE | ~12 lines: `app.openapi()` → JSON to stdout |
| `web/lib/openapi-types.ts` | CREATE (generated) | Full OpenAPI types output. Committed. Devs don't hand-edit. |
| `web/lib/types.ts` | MODIFY | 7 portfolio types become re-exports; other 10 types unchanged |
| `web/package.json` | MODIFY | `openapi-typescript` devDep + `codegen` + `codegen:check` scripts |
| `web/package-lock.json` | UPDATE | npm-managed; reflects the new dep |
| `server/.gitignore` (or root) | MODIFY | Add `openapi.json` |

No router changes. No Pydantic schema changes. No test file changes. No consumer file changes. No new top-level dirs.

---

## 10. Verification

The implementation is done when all of the following hold:

1. **`cd web && npm run codegen`** completes without error; `web/lib/openapi-types.ts` is created/updated; `server/openapi.json` exists temporarily during the run.
2. **`cd web && npm run codegen:check`** exits 0 immediately after `codegen` (proves drift-check baseline).
3. **`cd web && npm run typecheck`** passes — all 10 consumer files type-check against the generated types.
4. **Spot-check**: open `web/lib/openapi-types.ts`, find `components["schemas"]["DecisionPin"]` — it has `trade_date: string`, `rating: string`, `status: components["schemas"]["MemoryEntryStatus"]` (or inline equivalent), `raw_return: number | null`.
5. **Smoke drift test**: temporarily add a field to the Pydantic `DecisionPin`, run `codegen:check` — exits non-zero with a diff showing the new field. Revert the Pydantic change.
6. `git diff main..HEAD --name-only` shows only the 6 files listed in §9. No router/service/model/test drift.

---

## 11. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| **`app.openapi()` requires importing `app.main.app`, which loads the full FastAPI app at module import time** (DB engine creation, settings parsing, etc.). | This already happens for `pytest` and the dev server — no new path. The `export_openapi.py` script doesn't connect to the DB; `app.openapi()` is route-introspection only. |
| **`openapi-typescript` v7's output format differs from v6.** | We pin `^7` in `devDependencies`; major-version upgrades are explicit decisions, caught by `codegen:check` if the generated shape changes. |
| **The wrapper re-export pattern adds one indirection layer.** | Acceptable cost. The friendly-name layer is what makes the 10 consumer imports unchanged. Removing it would require a 10-file migration. |
| **`MemoryEntryOut` schema has no router consumer**, so it does not appear in `app.openapi()`. | This is FINE — `MemoryEntryOut` is not exported in `web/lib/types.ts` either (verified). The web app doesn't use it. If a future web consumer needs it, register a route that returns it. |
| **`openapi-typescript` may rename or restructure types in unexpected ways** for some Pydantic features (Literal vs Enum, discriminated unions, etc.). | The smoke step (V5) catches this — if the regen produces a shape the wrapper or consumers don't expect, it surfaces during PR review. |
| **Codegen output not deterministic across machines / Node versions.** | `openapi-typescript` v7 output IS deterministic (sorted, no timestamps). Verified by inspection of releases. If a future version becomes non-deterministic, pin to the last deterministic version. |

---

## 12. References

- v3+ followup #12 in PR #3's body
- `openapi-typescript` docs: https://openapi-ts.dev/
- FastAPI OpenAPI customization: https://fastapi.tiangolo.com/how-to/extending-openapi/
- Pre-existing hand-mirrored types: `web/lib/types.ts` (94 lines, 17 types)
- 10 consumer files identified via `grep -rn '@/lib/types' web --include='*.tsx' --include='*.ts'`
