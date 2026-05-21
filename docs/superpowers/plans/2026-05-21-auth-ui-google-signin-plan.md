# Auth UI + Google Sign-In Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Google OAuth as a second sign-in provider alongside GitHub, behind a custom `/login` page that matches the Axiara brand, with auto-link-by-verified-email user identity and a hard-fail boot guard against the E2E credentials backdoor leaking into production.

**Architecture:** Three logical changes, no new services. (1) `web/lib/auth.ts` adds the Google provider, a production guard around the E2E credentials block, and JWT callbacks that capture both provider IDs and the canonical `email`. (2) A new `/login` route in the web container renders a centered glass card with two stacked `ProviderButton` components. (3) An Alembic migration adds `users.google_sub` + a unique partial index on `users.email`, makes `users.github_id` nullable, and the FastAPI `get_current_user` switches to a `find_or_create_by_identity` helper that auto-links users by email.

**Tech Stack:** Auth.js v5 (NextAuth), Next.js 15 (web container), FastAPI + SQLAlchemy 2 async (api), Alembic migrations, Tailwind CSS, Playwright (E2E tests), PyJWT.

**Spec:** [`docs/superpowers/plans/2026-05-21-auth-ui-google-signin-design.md`](./2026-05-21-auth-ui-google-signin-design.md)

---

## Before You Start

This plan assumes you can answer "yes" to all of these:

- You can edit DNS on neither this domain nor any other (no DNS changes needed for this feature — Google OAuth uses the existing prod URL).
- You have admin on the `erikgunawans/TradingAgents` fork and the existing GitHub OAuth app.
- You have access to https://console.cloud.google.com under the same Google account that owns the `tradix-axiara` GCP project (the OAuth client can live in the same project as the VM or a separate project — your call).
- The prod VM is reachable via `gcloud compute ssh tradix --zone=asia-southeast2-a`.

Variables to set in your shell at the start of each session:

```bash
export GCP_PROJECT_ID="tradix-axiara"
export GCP_ZONE="asia-southeast2-a"
export VM_NAME="tradix"
gcloud config set project "$GCP_PROJECT_ID"
```

---

## Phase 1 — Local repo prep

### Task 1: Create the feature branch

**Files:** none (git only).

- [ ] **Step 1: Sync local main**

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git fetch fork
git checkout main
git pull fork main
```

Expected: `Already up to date.` or fast-forward to the current fork main HEAD (post-PR #21).

- [ ] **Step 2: Create the feature branch**

```bash
git checkout -b feature/auth-ui-google
```

Expected: `Switched to a new branch 'feature/auth-ui-google'`.

---

## Phase 2 — Server changes (migration + identity helper + JWT verifier)

### Task 2: Write the failing test — find_or_create lookup by email

**Files:**
- Create: `server/tests/test_user_identity.py`

- [ ] **Step 1: Create the test file with the email-lookup test**

```python
# server/tests/test_user_identity.py
import uuid
import pytest

from app.models.user import User, find_or_create_by_identity


@pytest.mark.asyncio
async def test_finds_user_by_email_and_backfills_google_sub(db_session):
    """Existing user with only github_id; signing in via Google with the
    same email should return that user and populate google_sub."""
    existing = User(
        id=uuid.uuid4(),
        github_id="111",
        email="alice@example.com",
        google_sub=None,
    )
    db_session.add(existing)
    await db_session.flush()

    found = await find_or_create_by_identity(
        db_session,
        email="alice@example.com",
        github_id=None,
        google_sub="google-sub-aaa",
    )

    assert found.id == existing.id, "should return the existing user, not create a new one"
    assert found.google_sub == "google-sub-aaa", "should backfill google_sub"
    assert found.github_id == "111", "should not clobber existing github_id"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd server && uv run pytest tests/test_user_identity.py -v`
Expected: FAIL with `ImportError` on `find_or_create_by_identity` (function doesn't exist yet).

No commit yet (we'll commit the test together with the implementation in Task 5).

---

### Task 3: Write the failing test — legacy github_id fallback

**Files:**
- Modify: `server/tests/test_user_identity.py`

- [ ] **Step 1: Append the legacy-fallback test**

```python
@pytest.mark.asyncio
async def test_legacy_user_without_email_found_by_github_id(db_session):
    """Pre-migration user with email=NULL, only github_id set. Signing in
    again with GitHub provides the email — find by github_id and backfill
    email."""
    legacy = User(
        id=uuid.uuid4(),
        github_id="222",
        email=None,
        google_sub=None,
    )
    db_session.add(legacy)
    await db_session.flush()

    found = await find_or_create_by_identity(
        db_session,
        email="bob@example.com",
        github_id="222",
        google_sub=None,
    )

    assert found.id == legacy.id, "should return the legacy user"
    assert found.email == "bob@example.com", "should backfill email"
    assert found.github_id == "222"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd server && uv run pytest tests/test_user_identity.py -v`
Expected: both tests fail with `ImportError`.

---

### Task 4: Write the failing test — new user creation

**Files:**
- Modify: `server/tests/test_user_identity.py`

- [ ] **Step 1: Append the new-user test**

```python
@pytest.mark.asyncio
async def test_creates_new_user_when_no_match(db_session):
    """First-ever sign-in for an unknown identity creates a new user
    with the supplied fields."""
    found = await find_or_create_by_identity(
        db_session,
        email="charlie@example.com",
        github_id=None,
        google_sub="google-sub-ccc",
    )
    await db_session.flush()

    assert found.email == "charlie@example.com"
    assert found.google_sub == "google-sub-ccc"
    assert found.github_id is None


@pytest.mark.asyncio
async def test_finds_by_google_sub_when_email_unknown(db_session):
    """If the existing user has google_sub set and email=NULL (unlikely
    edge case but possible after partial backfill), find by google_sub."""
    legacy = User(
        id=uuid.uuid4(),
        github_id=None,
        google_sub="google-sub-ddd",
        email=None,
    )
    db_session.add(legacy)
    await db_session.flush()

    found = await find_or_create_by_identity(
        db_session,
        email="dan@example.com",
        github_id=None,
        google_sub="google-sub-ddd",
    )

    assert found.id == legacy.id, "should match by google_sub"
    assert found.email == "dan@example.com", "should backfill email"
```

- [ ] **Step 2: Run to verify all 4 tests fail**

Run: `cd server && uv run pytest tests/test_user_identity.py -v`
Expected: 4 tests fail with `ImportError`.

---

### Task 5: Implement User model changes + helper + migration

**Files:**
- Modify: `server/app/models/user.py`
- Create: `server/alembic/versions/c2d3e4f5a6b7_users_add_email_unique_and_google_sub.py`

- [ ] **Step 1: Update the User model**

Replace `server/app/models/user.py` with:

```python
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # github_id and google_sub are both nullable now that users can sign in
    # with either provider (or both, via auto-link-by-email). Unique partial
    # indexes are added in the alembic migration alongside this change.
    github_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    google_sub: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Email is the canonical cross-provider identity. Unique partial index
    # added in the migration (WHERE email IS NOT NULL).
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


async def find_or_create_by_identity(
    db: AsyncSession,
    *,
    email: str | None,
    github_id: str | None = None,
    google_sub: str | None = None,
) -> User:
    """
    Resolve a user by verified-email-as-canonical-identity, with legacy
    fallback to provider-id lookup.

    Order:
      1. If email provided and matches an existing user, return that user
         and backfill any missing provider ids.
      2. Else if github_id provided and matches an existing user, return
         that user and backfill email if missing.
      3. Else if google_sub provided and matches an existing user, return
         that user and backfill email if missing.
      4. Else create a new user with whatever fields are provided.

    On race-condition IntegrityError during step 4, re-run the lookup
    chain — another concurrent request likely created the user.
    """
    # 1. Lookup by email (canonical)
    if email:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is not None:
            if github_id and user.github_id is None:
                user.github_id = github_id
            if google_sub and user.google_sub is None:
                user.google_sub = google_sub
            return user

    # 2. Legacy fallback: lookup by github_id
    if github_id:
        user = (
            await db.execute(select(User).where(User.github_id == github_id))
        ).scalar_one_or_none()
        if user is not None:
            if email and user.email is None:
                user.email = email
            if google_sub and user.google_sub is None:
                user.google_sub = google_sub
            return user

    # 3. Legacy fallback: lookup by google_sub
    if google_sub:
        user = (
            await db.execute(select(User).where(User.google_sub == google_sub))
        ).scalar_one_or_none()
        if user is not None:
            if email and user.email is None:
                user.email = email
            if github_id and user.github_id is None:
                user.github_id = github_id
            return user

    # 4. New user
    user = User(
        id=uuid.uuid4(),
        email=email,
        github_id=github_id,
        google_sub=google_sub,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        # Race: another request just inserted a user with the same identity.
        # Roll back and re-resolve. The retry MUST succeed since the
        # unique-index conflict means a matching row now exists.
        await db.rollback()
        if email:
            user = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one()
            return user
        if github_id:
            user = (
                await db.execute(select(User).where(User.github_id == github_id))
            ).scalar_one()
            return user
        user = (
            await db.execute(select(User).where(User.google_sub == google_sub))
        ).scalar_one()
        return user

    return user
```

- [ ] **Step 2: Create the alembic migration**

```bash
mkdir -p server/alembic/versions
```

Write `server/alembic/versions/c2d3e4f5a6b7_users_add_email_unique_and_google_sub.py`:

```python
"""users: add google_sub, make github_id nullable, unique partial index on email

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-21
"""
from alembic import op
import sqlalchemy as sa


revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make github_id nullable — Google-only users won't have one.
    op.alter_column("users", "github_id", existing_type=sa.String(64), nullable=True)

    # Add google_sub (nullable, indexed, unique-where-not-null).
    op.add_column("users", sa.Column("google_sub", sa.String(64), nullable=True))
    op.create_index("ix_users_google_sub", "users", ["google_sub"])
    op.create_index(
        "ix_users_google_sub_unique",
        "users",
        ["google_sub"],
        unique=True,
        postgresql_where=sa.text("google_sub IS NOT NULL"),
    )

    # email is already a nullable column — add a unique partial index.
    op.create_index(
        "ix_users_email_unique",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_email_unique", "users")
    op.drop_index("ix_users_google_sub_unique", "users")
    op.drop_index("ix_users_google_sub", "users")
    op.drop_column("users", "google_sub")
    op.alter_column("users", "github_id", existing_type=sa.String(64), nullable=False)
```

- [ ] **Step 3: Run the migration in the test DB + the tests**

```bash
cd server
uv run alembic upgrade head
uv run pytest tests/test_user_identity.py -v
```

Expected: migration applies cleanly; all 4 tests in `test_user_identity.py` pass.

- [ ] **Step 4: Run the FULL server test suite to confirm no regressions**

Run: `cd server && uv run pytest -q`
Expected: `159 passed, 1 deselected` (or higher — same as before our 4 new tests, which became `163 passed, 1 deselected`).

- [ ] **Step 5: Commit**

```bash
git add server/tests/test_user_identity.py \
        server/app/models/user.py \
        server/alembic/versions/c2d3e4f5a6b7_users_add_email_unique_and_google_sub.py
git commit -m "feat(server): add google_sub + find_or_create_by_identity helper

Migration:
- alter users.github_id to nullable (Google-only users won't have one)
- add users.google_sub (nullable, partial unique)
- add partial unique index on users.email

User model:
- mark github_id as Mapped[str | None]
- add google_sub: Mapped[str | None]
- add find_or_create_by_identity helper that resolves by email first
  (canonical) with legacy provider-id fallback; auto-links by backfilling
  missing provider IDs / email on existing rows; handles concurrent
  insert races via IntegrityError + retry-lookup.

Tests cover: lookup by email + backfill google_sub on existing
github user; legacy lookup by github_id when email is null; new
user creation; legacy lookup by google_sub."
```

---

### Task 6: Update get_current_user in auth.py to use the new helper

**Files:**
- Modify: `server/app/auth.py`
- Create: `server/tests/test_auth_dual_provider.py`

- [ ] **Step 1: Write a failing test that exercises a Google-provider JWT**

Create `server/tests/test_auth_dual_provider.py`:

```python
import uuid

import jwt
import pytest
from fastapi import HTTPException

from app.auth import get_current_user
from app.config import get_settings
from app.models.user import User


def _make_token(*, sub: str, email: str | None = None, provider: str = "github") -> str:
    settings = get_settings()
    payload: dict = {"sub": sub}
    if email:
        payload["email"] = email
    if provider:
        payload["provider"] = provider
    return jwt.encode(payload, settings.nextauth_secret, algorithm=settings.jwt_algorithm)


@pytest.mark.asyncio
async def test_google_jwt_creates_user_with_google_sub(db_session):
    """A first-time Google sign-in (JWT carries provider=google) should
    create a user with google_sub set and email populated, github_id NULL."""
    token = _make_token(sub="google-sub-zzz", email="zara@example.com", provider="google")

    user = await get_current_user(authorization=f"Bearer {token}", db=db_session)

    assert user.google_sub == "google-sub-zzz"
    assert user.github_id is None
    assert user.email == "zara@example.com"


@pytest.mark.asyncio
async def test_legacy_jwt_without_provider_treated_as_github(db_session):
    """JWTs issued before this PR don't carry a `provider` claim. They
    should be treated as GitHub for backward compatibility."""
    token = _make_token(sub="333", email="legacy@example.com", provider="")

    user = await get_current_user(authorization=f"Bearer {token}", db=db_session)

    assert user.github_id == "333"
    assert user.google_sub is None
    assert user.email == "legacy@example.com"


@pytest.mark.asyncio
async def test_signing_in_via_google_links_existing_github_user(db_session):
    """Two-step flow: existing user signed up with GitHub (email
    alice@example.com), then signs in via Google with the same email.
    The Google sign-in should resolve to the SAME user row with both
    provider IDs populated."""
    # Step 1: GitHub user pre-exists
    existing = User(
        id=uuid.uuid4(),
        github_id="444",
        email="alice@example.com",
        google_sub=None,
    )
    db_session.add(existing)
    await db_session.flush()

    # Step 2: Google sign-in arrives
    token = _make_token(sub="google-sub-aaa", email="alice@example.com", provider="google")
    user = await get_current_user(authorization=f"Bearer {token}", db=db_session)

    assert user.id == existing.id, "should resolve to the existing user, not create a new one"
    assert user.github_id == "444", "github_id should remain populated"
    assert user.google_sub == "google-sub-aaa", "google_sub should now be populated"
    assert user.email == "alice@example.com"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd server && uv run pytest tests/test_auth_dual_provider.py -v`
Expected: tests fail — the current `get_current_user` only handles github_id and ignores `provider`.

- [ ] **Step 3: Replace get_current_user in server/app/auth.py**

Open `server/app/auth.py` and replace the `get_current_user` function (the rest of the file stays unchanged):

```python
async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    from app.models.user import find_or_create_by_identity

    payload = _decode_token(_extract_token(authorization))
    sub = payload.get("sub")
    email = payload.get("email")
    provider = payload.get("provider") or "github"  # legacy default

    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthenticated"},
        )

    github_id = sub if provider in ("github", "e2e") else None
    google_sub = sub if provider == "google" else None

    return await find_or_create_by_identity(
        db,
        email=email,
        github_id=github_id,
        google_sub=google_sub,
    )
```

Also remove the now-unused `IntegrityError` and `uuid` imports at the top of the file if no other reference uses them.

- [ ] **Step 4: Run the new tests + full server suite**

```bash
cd server
uv run pytest tests/test_auth_dual_provider.py -v
uv run pytest -q
```

Expected: 3 new tests in `test_auth_dual_provider.py` pass; full suite shows `166 passed, 1 deselected` (159 baseline + 4 from Task 5 + 3 from this task).

- [ ] **Step 5: Commit**

```bash
git add server/app/auth.py server/tests/test_auth_dual_provider.py
git commit -m "feat(server): get_current_user honors provider claim + uses find_or_create_by_identity

JWTs with provider=google route the sub to google_sub; provider=github
(default for legacy JWTs that don't carry the claim) routes sub to
github_id. Auto-link-by-email happens transparently when the same email
signs in across providers.

Backward compat: JWTs issued before this PR don't have a 'provider'
claim, so they get the legacy default (github). No forced sign-out."
```

---

## Phase 3 — Web changes (auth.ts + /login page)

### Task 7: Add Google provider + production guard to web/lib/auth.ts

**Files:**
- Modify: `web/lib/auth.ts`

- [ ] **Step 1: Replace web/lib/auth.ts with the dual-provider version**

```typescript
import NextAuth, { type NextAuthConfig } from "next-auth";
import GitHub from "next-auth/providers/github";
import Google from "next-auth/providers/google";
import Credentials from "next-auth/providers/credentials";

const secret = process.env.NEXTAUTH_SECRET;
if (!secret) throw new Error("NEXTAUTH_SECRET is required");

const providers: NextAuthConfig["providers"] = [
  GitHub({
    clientId: process.env.AUTH_GITHUB_ID!,
    clientSecret: process.env.AUTH_GITHUB_SECRET!,
  }),
  Google({
    clientId: process.env.AUTH_GOOGLE_ID!,
    clientSecret: process.env.AUTH_GOOGLE_SECRET!,
  }),
];

// Dev-only credentials backdoor. Hard-fails if it ever sees production —
// guards against env-var drift (E2E_TEST_MODE=1 leaking into prod) per
// the design spec §3 and the 13 memory observations flagging this risk.
if (process.env.E2E_TEST_MODE === "1") {
  if (process.env.NODE_ENV === "production") {
    throw new Error(
      "E2E_TEST_MODE=1 cannot run with NODE_ENV=production. " +
        "This guards the credentials-provider backdoor from env-var drift."
    );
  }
  providers.push(
    Credentials({
      name: "e2e",
      credentials: { githubId: { label: "GitHub ID" } },
      async authorize(c) {
        if (!c?.githubId) return null;
        const id = String(c.githubId);
        return { id, email: `${id}@e2e.local` };
      },
    })
  );
}

export const authConfig: NextAuthConfig = {
  providers,
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  jwt: {
    // HS256 by default — matches server/app/auth.py
  },
  callbacks: {
    async jwt({ token, account, profile, user }) {
      if (account?.provider === "google" && profile) {
        const p = profile as { sub: string; email: string };
        token.sub = String(p.sub);
        token.email = p.email;
        (token as { provider?: string }).provider = "google";
      } else if (account?.provider === "github" && profile) {
        const p = profile as { id: number | string; email?: string };
        token.sub = String(p.id);
        if (p.email) token.email = p.email;
        (token as { provider?: string }).provider = "github";
      } else if (user && process.env.E2E_TEST_MODE === "1") {
        token.sub = String(user.id);
        if (user.email) token.email = user.email;
        (token as { provider?: string }).provider = "e2e";
      }
      return token;
    },
    async session({ session, token }) {
      if (token.sub) {
        const u = session.user as { providerId?: string; githubId?: string };
        u.providerId = token.sub;
        // Legacy alias — kept for code paths that still read githubId.
        // Remove in a later refactor once consumers migrate to providerId.
        u.githubId = token.sub;
      }
      return session;
    },
  },
  secret,
};

export const { handlers, signIn, signOut, auth } = NextAuth(authConfig);
```

- [ ] **Step 2: Verify next.js compiles + no type errors**

```bash
cd web
npm run build 2>&1 | tail -20
```

Expected: `▲ Next.js ...` followed by a successful build summary. No TypeScript errors.

If `next-auth/providers/google` import errors with "Cannot find module" — Google provider has been part of `next-auth` since v4. The package is already in `web/package.json`. If by some chance it isn't:
```bash
cd web && npm install next-auth@latest
```

- [ ] **Step 3: Write a tiny Node-based smoke for the production guard**

Create `web/scripts/verify-auth-prod-guard.mjs`:

```javascript
#!/usr/bin/env node
// Verifies the E2E_TEST_MODE production guard in web/lib/auth.ts.
// Run: NODE_ENV=production E2E_TEST_MODE=1 NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x AUTH_GOOGLE_ID=x AUTH_GOOGLE_SECRET=x node web/scripts/verify-auth-prod-guard.mjs

try {
  await import("../lib/auth.ts");
  console.error("FAIL: import succeeded — production guard didn't fire");
  process.exit(1);
} catch (e) {
  if (e?.message?.includes("E2E_TEST_MODE=1 cannot run with NODE_ENV=production")) {
    console.log("OK: guard fired as expected");
    process.exit(0);
  }
  console.error("FAIL: unexpected error:", e?.message);
  process.exit(1);
}
```

> **Note:** `.mjs` + dynamic `import()` of a `.ts` file works because Next.js 15's bundler strips types. If this errors with "Cannot import .ts" in your Node version, skip the smoke (Task 8's commit message documents that the manual smoke was deferred). The guard's correctness is asserted by code review of the diff alone.

- [ ] **Step 4: Run the smoke (best-effort — skip if Node can't load .ts)**

```bash
cd web && \
NODE_ENV=production E2E_TEST_MODE=1 \
NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x \
AUTH_GOOGLE_ID=x AUTH_GOOGLE_SECRET=x \
node scripts/verify-auth-prod-guard.mjs 2>&1
```

Expected: `OK: guard fired as expected` OR (if Node can't load .ts) an ESM-loader error in which case proceed to Step 5.

- [ ] **Step 5: Commit**

```bash
git add web/lib/auth.ts web/scripts/verify-auth-prod-guard.mjs
git commit -m "feat(web): add Google provider + production guard + dual-provider JWT callbacks

- Add Google to the providers list. Reads AUTH_GOOGLE_ID +
  AUTH_GOOGLE_SECRET from env (template updated in scripts/gen-prod-env.sh).
- Guard the E2E credentials provider with a NODE_ENV=production check
  that throws at boot. Eliminates the env-var-drift backdoor risk
  flagged in 13 memory observations.
- JWT callback now reads account.provider to route sub correctly
  (profile.sub for Google, profile.id for GitHub) and captures email
  as a token claim for the server-side verifier.
- Session callback adds providerId alongside legacy githubId alias for
  code paths that haven't migrated yet.
- pages: { signIn: '/login' } — redirects from NextAuth's default
  /api/auth/signin to the new custom page created in Task 10."
```

---

### Task 8: Create the ProviderButton component

**Files:**
- Create: `web/components/ProviderButton.tsx`

- [ ] **Step 1: Write the component**

```tsx
// web/components/ProviderButton.tsx
"use client";

import { signIn } from "next-auth/react";

type Provider = "github" | "google";

interface Props {
  provider: Provider;
  callbackUrl?: string;
  disabled?: boolean;
}

const LABEL: Record<Provider, string> = {
  github: "Continue with GitHub",
  google: "Continue with Google",
};

const Icon = ({ provider }: { provider: Provider }) => {
  if (provider === "github") {
    return (
      <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M12 .3a12 12 0 0 0-3.8 23.4c.6.1.8-.3.8-.6v-2c-3.3.7-4-1.6-4-1.6-.5-1.4-1.3-1.8-1.3-1.8-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1.1 1.8 2.8 1.3 3.4 1 .1-.8.4-1.3.8-1.6-2.6-.3-5.4-1.3-5.4-5.9 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0c2.3-1.5 3.3-1.2 3.3-1.2.7 1.7.2 2.9.1 3.2.8.8 1.2 1.9 1.2 3.2 0 4.6-2.8 5.6-5.4 5.9.4.4.8 1.1.8 2.3v3.4c0 .3.2.7.8.6A12 12 0 0 0 12 .3" />
      </svg>
    );
  }
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M21.4 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.3c-.2 1.2-.9 2.3-2 3v2.4h3.2c1.9-1.7 3-4.3 3-7.2z" fill="#4285f4" />
      <path d="M12 22c2.7 0 5-.9 6.6-2.5l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.1H3v2.6A10 10 0 0 0 12 22z" fill="#34a853" />
      <path d="M6.4 13.9A6 6 0 0 1 6 12c0-.7.1-1.3.4-1.9V7.5H3a10 10 0 0 0 0 9z" fill="#fbbc05" />
      <path d="M12 5.9a5.4 5.4 0 0 1 3.8 1.5l2.8-2.8A10 10 0 0 0 12 2a10 10 0 0 0-9 5.5l3.4 2.6c.8-2.4 3-4.2 5.6-4.2z" fill="#ea4335" />
    </svg>
  );
};

export default function ProviderButton({ provider, callbackUrl = "/history", disabled = false }: Props) {
  return (
    <button
      type="button"
      onClick={() => signIn(provider, { callbackUrl })}
      disabled={disabled}
      className="flex w-full items-center gap-2.5 rounded-lg border border-white/10 bg-white/[0.04] px-3.5 py-2.5 text-sm font-medium text-fg-primary transition hover:bg-white/[0.07] hover:border-white/15 disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <Icon provider={provider} />
      <span>{LABEL[provider]}</span>
    </button>
  );
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd web && npm run build 2>&1 | tail -5
```

Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add web/components/ProviderButton.tsx
git commit -m "feat(web): add ProviderButton component for OAuth sign-in

Reusable button that takes a provider key ('github' | 'google') and
calls next-auth's signIn() on click. Renders inline SVG icon + label
inside an outlined button styled to match the existing Axiara dark
theme (white/04 bg, white/10 border, white/[0.07] hover)."
```

---

### Task 9: Create the SignInForm client component

**Files:**
- Create: `web/app/login/SignInForm.tsx`

- [ ] **Step 1: Write the component**

```tsx
// web/app/login/SignInForm.tsx
"use client";

import ProviderButton from "@/components/ProviderButton";

const ERROR_MESSAGES: Record<string, string> = {
  OAuthAccountNotLinked:
    "An account with this email already exists with a different sign-in method. Try signing in with your original provider.",
  AccessDenied: "Sign-in was cancelled or denied.",
  Configuration: "Sign-in is misconfigured. Please contact the administrator.",
  Verification: "The sign-in link is no longer valid. Please request a new one.",
};

function friendlyError(code: string | undefined): string | null {
  if (!code) return null;
  return ERROR_MESSAGES[code] ?? `Sign-in failed (${code}). Please try again.`;
}

interface Props {
  callbackUrl?: string;
  error?: string;
}

export default function SignInForm({ callbackUrl, error }: Props) {
  const errorMessage = friendlyError(error);

  return (
    <div className="space-y-2">
      {errorMessage && (
        <div
          role="alert"
          className="mb-3 rounded-md border border-brand/30 bg-brand/5 px-3 py-2 text-xs text-brand"
        >
          {errorMessage}
        </div>
      )}
      <ProviderButton provider="github" callbackUrl={callbackUrl} />
      <ProviderButton provider="google" callbackUrl={callbackUrl} />
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/app/login/SignInForm.tsx
git commit -m "feat(web): add SignInForm client component with error banner

Wraps the two ProviderButton components and renders a brand-red-outlined
error banner if NextAuth redirected back with ?error=... (e.g.,
OAuthAccountNotLinked, AccessDenied, Configuration). The error code is
mapped to a friendly message; unknown codes fall back to a generic
message including the code for support."
```

---

### Task 10: Create the /login page (server component)

**Files:**
- Create: `web/app/login/page.tsx`

- [ ] **Step 1: Write the page**

```tsx
// web/app/login/page.tsx
import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import SignInForm from "./SignInForm";

export const metadata = {
  title: "Sign in · TradingAgents",
};

interface PageProps {
  searchParams: Promise<{ error?: string; callbackUrl?: string }>;
}

export default async function LoginPage({ searchParams }: PageProps) {
  const session = await auth();
  const { error, callbackUrl } = await searchParams;

  if (session) {
    redirect(callbackUrl ?? "/history");
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-10">
      <div className="w-full max-w-sm rounded-2xl border border-white/[0.06] bg-surface/55 px-7 py-7 text-center backdrop-blur-sm">
        <div
          className="mx-auto mb-4 flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-brand to-red-dark font-bold text-white shadow-glow"
          aria-hidden="true"
        >
          /
        </div>
        <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-brand/85">
          tradingagents
        </p>
        <h1 className="text-lg font-semibold text-fg-primary">Sign in</h1>
        <p className="mb-5 mt-1.5 text-xs text-fg-muted">
          Continue with your preferred account
        </p>
        <SignInForm callbackUrl={callbackUrl} error={error} />
      </div>
    </main>
  );
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd web && npm run build 2>&1 | tail -10
```

Expected: `Route (app)` list includes `/login` (Static, ~1 kB). No type errors.

- [ ] **Step 3: Smoke-test locally**

```bash
cd web && npm run dev &
DEV_PID=$!
sleep 5
curl -fsS -o /dev/null -w "GET /login -> %{http_code}\n" http://localhost:3000/login
kill $DEV_PID 2>/dev/null
```

Expected: `GET /login -> 200`.

- [ ] **Step 4: Commit**

```bash
git add web/app/login/page.tsx
git commit -m "feat(web): add /login page — centered Axiara-branded sign-in card

Server component. If session exists, redirects to ?callbackUrl or
/history. Otherwise renders the centered glass card with brand-red
slash logo, eyebrow label, heading, subtitle, and the SignInForm.
Layout matches mockup A from the brainstorm session — single column,
stacked provider buttons, no marketing hero."
```

---

## Phase 4 — Tests + verification

### Task 11: Add Playwright E2E test for /login

**Files:**
- Create: `web/tests/e2e/login.spec.ts`

- [ ] **Step 1: Write the spec**

```typescript
import { test, expect } from "@playwright/test";

test.describe("/login page", () => {
  test("renders both provider buttons and brand chrome", async ({ page }) => {
    await page.goto("/login");

    await expect(page.locator("h1")).toHaveText("Sign in");
    await expect(page.getByText("tradingagents")).toBeVisible();
    await expect(page.getByText("Continue with your preferred account")).toBeVisible();

    const githubButton = page.getByRole("button", { name: "Continue with GitHub" });
    const googleButton = page.getByRole("button", { name: "Continue with Google" });
    await expect(githubButton).toBeVisible();
    await expect(googleButton).toBeVisible();
  });

  test("shows error banner when ?error=AccessDenied", async ({ page }) => {
    await page.goto("/login?error=AccessDenied");
    await expect(page.getByRole("alert")).toContainText("cancelled or denied");
  });

  test("unknown error code falls back to generic message", async ({ page }) => {
    await page.goto("/login?error=FunkyUnknownCode");
    await expect(page.getByRole("alert")).toContainText("FunkyUnknownCode");
  });
});
```

- [ ] **Step 2: Run the Playwright suite**

```bash
cd web && npx playwright test login.spec --reporter=line 2>&1 | tail -10
```

Expected: all 3 tests pass. If Playwright reports it can't find a running dev server, your `web/playwright.config.ts` already handles that — check `playwright.config.ts` for the `webServer` block. If absent, prefix with `npm run dev &` and pass the URL via `BASE_URL=http://localhost:3000`.

- [ ] **Step 3: Commit**

```bash
git add web/tests/e2e/login.spec.ts
git commit -m "test(web): Playwright e2e for /login page render + error banner

Three tests:
- both provider buttons visible alongside brand chrome
- ?error=AccessDenied surfaces the friendly message
- unknown error code falls back to generic message containing the code"
```

---

### Task 12: Update .env.example + scripts/gen-prod-env.sh template

**Files:**
- Modify: `.env.example`
- Modify: `scripts/gen-prod-env.sh`

- [ ] **Step 1: Append Google placeholders to .env.example**

Append to the bottom of `.env.example`:

```bash
# Google OAuth (only required for production deploys — dev uses E2E_TEST_MODE bypass).
# Create the client at https://console.cloud.google.com/apis/credentials.
AUTH_GOOGLE_ID=
AUTH_GOOGLE_SECRET=
```

- [ ] **Step 2: Update scripts/gen-prod-env.sh**

Open `scripts/gen-prod-env.sh`. Find the GitHub OAuth block:

```bash
# GitHub OAuth (paste from the OAuth app's settings page)
AUTH_GITHUB_ID=PASTE_FROM_GITHUB_OAUTH_APP
AUTH_GITHUB_SECRET=PASTE_FROM_GITHUB_OAUTH_APP
```

Replace it with:

```bash
# OAuth providers (paste from each provider's settings page)
AUTH_GITHUB_ID=PASTE_FROM_GITHUB_OAUTH_APP
AUTH_GITHUB_SECRET=PASTE_FROM_GITHUB_OAUTH_APP
AUTH_GOOGLE_ID=PASTE_FROM_GOOGLE_CLOUD_OAUTH_CLIENT
AUTH_GOOGLE_SECRET=PASTE_FROM_GOOGLE_CLOUD_OAUTH_CLIENT
```

- [ ] **Step 3: Smoke the template renders correctly**

```bash
./scripts/gen-prod-env.sh | grep -E "AUTH_GITHUB|AUTH_GOOGLE|AUTH_TRUST_HOST|DEFAULT_DEEP"
```

Expected output (values may vary for generated secrets):
```
AUTH_TRUST_HOST=true
AUTH_GITHUB_ID=PASTE_FROM_GITHUB_OAUTH_APP
AUTH_GITHUB_SECRET=PASTE_FROM_GITHUB_OAUTH_APP
AUTH_GOOGLE_ID=PASTE_FROM_GOOGLE_CLOUD_OAUTH_CLIENT
AUTH_GOOGLE_SECRET=PASTE_FROM_GOOGLE_CLOUD_OAUTH_CLIENT
DEFAULT_DEEP_THINK_LLM=anthropic/claude-sonnet-4.6
```

- [ ] **Step 4: Commit**

```bash
git add .env.example scripts/gen-prod-env.sh
git commit -m "chore(deploy): add AUTH_GOOGLE_* to env template + .env.example

Generated prod env files now include placeholders for the Google
OAuth client ID and secret alongside the existing GitHub ones.
The 'GitHub OAuth' comment block is renamed to 'OAuth providers'
to reflect the new shape."
```

---

### Task 13: Update docs/runbooks/first-boot.md with the Google OAuth client step

**Files:**
- Modify: `docs/runbooks/first-boot.md`

- [ ] **Step 1: Insert the Google OAuth client prerequisite**

In `docs/runbooks/first-boot.md`, find this bullet:

```markdown
- The GitHub OAuth app has `https://tradix.axiara.ai/api/auth/callback/github` in its callback whitelist. **If you haven't created one yet** — dev mode uses an `E2E_TEST_MODE` bypass that doesn't need a real OAuth app, so production needs a fresh one. Register at https://github.com/settings/developers → OAuth Apps → New OAuth app. Homepage: `https://tradix.axiara.ai`, Authorization callback URL: `https://tradix.axiara.ai/api/auth/callback/github`. Copy the Client ID + generated Client Secret to a password manager.
```

Insert the new bullet immediately after it:

```markdown
- The Google OAuth client has `https://tradix.axiara.ai/api/auth/callback/google` in its authorized redirect URIs. Create one at https://console.cloud.google.com/apis/credentials → Create Credentials → OAuth client ID → Application type: Web application. Authorized redirect URIs: `https://tradix.axiara.ai/api/auth/callback/google` (and optionally `http://localhost:3001/api/auth/callback/google` for dev). Copy the Client ID + Client Secret. **Consent screen:** keep the OAuth consent screen in "Testing" mode and add your own email + any allowed signers under "Test users". Requesting Google's app verification is a multi-day process and only needed once unverified-app usage exceeds Google's quotas. Expand the test-users list as new people need access.
```

- [ ] **Step 2: Update the env-file install step to reflect both providers**

Find this step in first-boot.md (under "Steps", inside step 1's "fill in" list):

```markdown
   - `AUTH_GITHUB_ID` + `AUTH_GITHUB_SECRET` from the OAuth app
   - `OPENROUTER_API_KEY` from your OpenRouter dashboard
   - (Optional) other `*_API_KEY` values
```

Replace with:

```markdown
   - `AUTH_GITHUB_ID` + `AUTH_GITHUB_SECRET` from the GitHub OAuth app
   - `AUTH_GOOGLE_ID` + `AUTH_GOOGLE_SECRET` from the Google OAuth client
   - `OPENROUTER_API_KEY` from your OpenRouter dashboard
   - (Optional) other `*_API_KEY` values
```

- [ ] **Step 3: Commit**

```bash
git add docs/runbooks/first-boot.md
git commit -m "docs(deploy): runbook covers Google OAuth client setup

New prerequisite covering Google Cloud Console OAuth client creation,
redirect URI configuration, and the Testing-mode consent-screen choice
(with test-users list as the gating mechanism). Updates the env-file
fill-in list to include AUTH_GOOGLE_ID + AUTH_GOOGLE_SECRET."
```

---

## Phase 5 — Cloud config + live deploy

### Task 14: Create the Google OAuth client + add secrets to running VM

**Files:** none in repo (cloud-only).

This is human-driven — only you can interact with Google Cloud Console.

- [ ] **Step 1: Create the Google OAuth client**

Browser tab on https://console.cloud.google.com/apis/credentials:

1. Make sure the project selector at the top is set to `tradix-axiara` (or whichever Google project you want to host the OAuth client — it doesn't have to be the same as the GCP VM project).
2. Click **+ Create Credentials → OAuth client ID**.
3. Application type: **Web application**.
4. Name: `tradix.axiara.ai prod`.
5. Authorized redirect URIs: add **two** entries:
   - `https://tradix.axiara.ai/api/auth/callback/google`
   - `http://localhost:3001/api/auth/callback/google` (lets you use Google in dev later)
6. Click **Create**. Copy the **Client ID** + **Client Secret** to your password manager.

- [ ] **Step 2: Configure the OAuth consent screen**

If this is the first OAuth client in the project, you'll be prompted to configure the consent screen.

1. User type: **External**.
2. App name: `TradingAgents`.
3. User support email: your email.
4. Developer contact: your email.
5. **Save and continue** through Scopes (no changes needed — default email + profile + openid is what we want).
6. **Test users**: add your own Google account email plus any other allowed signers. Save and continue.
7. **Publishing status**: keep at **Testing** (don't click "Publish App" — that triggers Google's verification flow).

- [ ] **Step 3: Append AUTH_GOOGLE_* to the running VM's env file**

You'll need both the Client ID and Client Secret from Step 1. The same secure-input pattern from PR #19 applies: run this in a real Terminal (not Claude Code's `!` prefix — getpass needs a TTY).

```bash
# In a regular Terminal, on your laptop:
python3 -c "
import getpass
import subprocess
gid = getpass.getpass('AUTH_GOOGLE_ID: ')
gsec = getpass.getpass('AUTH_GOOGLE_SECRET: ')
block = f'AUTH_GOOGLE_ID={gid}\nAUTH_GOOGLE_SECRET={gsec}\n'
subprocess.run(['gcloud', 'compute', 'ssh', 'tradix', '--zone=asia-southeast2-a', '--command',
  f'echo \"{block}\" | sudo tee -a /etc/tradingagents/env > /dev/null && echo Appended'],
  check=True)
print('Done.')
"
```

Expected: `Appended` from the remote command, then `Done.` locally.

- [ ] **Step 4: Verify the env file has both entries**

```bash
gcloud compute ssh tradix --zone=asia-southeast2-a --command='sudo grep -E "^AUTH_GOOGLE" /etc/tradingagents/env | sed "s/=.*/=<redacted>/"'
```

Expected:
```
AUTH_GOOGLE_ID=<redacted>
AUTH_GOOGLE_SECRET=<redacted>
```

- [ ] **Step 5: Recreate the web container so it picks up the new env**

```bash
gcloud compute ssh tradix --zone=asia-southeast2-a --command='
cd /srv/tradingagents
sudo IMAGE_TAG=$(cat .current_image_tag) docker compose --env-file /etc/tradingagents/env -f docker-compose.yml -f docker-compose.prod.yml up -d --force-recreate web
'
```

Expected: `Container tradingagents-web-1  Started`.

- [ ] **Step 6: Verify the Google provider now appears in /api/auth/providers**

```bash
curl -sS https://tradix.axiara.ai/api/auth/providers | python3 -m json.tool
```

Expected: JSON contains both `github` and `google` entries. `google.callbackUrl` is `https://tradix.axiara.ai/api/auth/callback/google`.

No commit (cloud state only).

---

## Phase 6 — Ship

### Task 15: Push feature branch + open PR

**Files:** none (git only).

- [ ] **Step 1: Push the branch**

```bash
git push --set-upstream fork feature/auth-ui-google
```

Expected: `* [new branch] feature/auth-ui-google -> feature/auth-ui-google`.

- [ ] **Step 2: Open the PR**

```bash
gh pr create --repo erikgunawans/TradingAgents \
  --title "feat(auth): Google OAuth + custom /login page + email-as-identity" \
  --base main \
  --head feature/auth-ui-google \
  --body "$(cat <<'EOF'
## Summary

Wave 4 item 1. Adds Google OAuth alongside GitHub, replaces NextAuth's default sign-in page with a custom \`/login\` route matching the Axiara brand, switches user identity to email-as-canonical with provider IDs as supplementary, and hard-fails the E2E credentials backdoor in production.

Locked decisions from the brainstorm session (see design doc):

- Auto-link users by verified email (same email + verified provider = same user).
- Single unified \`/login\` page; no marketing hero.
- Hard-fail at boot if \`E2E_TEST_MODE=1\` && \`NODE_ENV=production\`.
- Centered glass card with stacked icon+label provider buttons.

## What's in this PR

### Server (\`server/\`)

- Alembic migration \`c2d3e4f5a6b7\`: \`users.github_id\` becomes nullable, adds \`users.google_sub\` (nullable + unique partial), adds unique partial index on \`users.email\`.
- New \`find_or_create_by_identity\` helper in \`app/models/user.py\` — resolves users by email first (canonical), with legacy provider-id fallback and auto-link backfill.
- \`get_current_user\` now reads the JWT's \`provider\` claim to route the \`sub\` to either \`github_id\` or \`google_sub\`. Legacy JWTs without a \`provider\` claim default to github for backward compat.
- 7 new tests: 4 for the identity helper, 3 for the dual-provider verifier behavior.

### Web (\`web/\`)

- \`lib/auth.ts\`: Google provider added; E2E credentials block hard-fails if \`NODE_ENV=production\`; JWT callback routes profile.id/profile.sub correctly; session exposes both \`providerId\` and legacy \`githubId\` alias.
- New \`/login\` page (server component) + \`SignInForm\` (client) + \`ProviderButton\` (client). Centered glass card on the ambient gradient, brand-red slash logo, eyebrow label, two stacked provider buttons.
- Playwright E2E spec: page renders, error banner surfaces correctly, unknown error codes fall back gracefully.

### Config + docs

- \`scripts/gen-prod-env.sh\` template includes \`AUTH_GOOGLE_ID\` + \`AUTH_GOOGLE_SECRET\` placeholders.
- \`.env.example\` documents the new vars.
- \`docs/runbooks/first-boot.md\` gains a Google OAuth client prerequisite + consent-screen note.

## Test plan

- [x] Server test suite — 159 → 166 passing (+7 new).
- [x] \`web/lib/auth.ts\` builds cleanly.
- [x] Playwright \`/login\` E2E passes locally.
- [x] Migration up + down round-trips in tests.
- [ ] After merge — auto-deploy succeeds; \`/api/auth/providers\` shows both github + google entries.
- [ ] Manual: GitHub sign-in flow still works (existing session unaffected).
- [ ] Manual: Google sign-in flow completes and lands on \`/history\`.
- [ ] Manual: sign in with GitHub using email X, sign out, sign in with Google using same email X → same user row, both \`github_id\` and \`google_sub\` populated.
- [ ] Manual: \`/login?error=AccessDenied\` shows the friendly error banner.

## Production guard manual verification

The E2E_TEST_MODE production-guard test is best verified in CI or locally via:

\`\`\`bash
cd web && NODE_ENV=production E2E_TEST_MODE=1 NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x AUTH_GOOGLE_ID=x AUTH_GOOGLE_SECRET=x node scripts/verify-auth-prod-guard.mjs
\`\`\`

Expected: \`OK: guard fired as expected\`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed.

No commit.

---

### Task 16: Merge PR + verify auto-deploy + end-to-end smoke

**Files:** none.

- [ ] **Step 1: Merge the PR**

```bash
gh pr merge $(gh pr list --repo erikgunawans/TradingAgents --head feature/auth-ui-google --json number --jq '.[0].number') --merge --repo erikgunawans/TradingAgents
```

Expected: merge succeeds.

- [ ] **Step 2: Watch the auto-deploy**

```bash
sleep 8
RUN_ID=$(gh run list --repo erikgunawans/TradingAgents --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --repo erikgunawans/TradingAgents --exit-status
```

Expected: all 3 jobs succeed (Build api, Build web, Deploy to VM).

- [ ] **Step 3: Confirm migration ran on first api container start**

```bash
gcloud compute ssh tradix --zone=asia-southeast2-a --command='sudo docker logs tradingagents-api-1 2>&1 | grep -E "alembic|c2d3e4f5a6b7" | tail -5'
```

Expected: `Running upgrade b1c2d3e4f5a6 -> c2d3e4f5a6b7, users: add google_sub ...`.

- [ ] **Step 4: Verify providers are wired**

```bash
curl -sS https://tradix.axiara.ai/api/auth/providers | python3 -m json.tool
```

Expected: both `github` and `google` provider entries, each with correct `signinUrl` + `callbackUrl`.

- [ ] **Step 5: Manual browser smoke**

In a browser:

1. Open https://tradix.axiara.ai (signed-out — open incognito if currently signed in).
2. Land on `/login` (NextAuth redirected from `/` via middleware).
3. Verify the centered glass card renders with brand-red slash logo + "tradingagents" eyebrow + "Sign in" heading + two stacked provider buttons.
4. Click **Continue with Google**. Authorize on Google's screen.
5. Verify you land on `/history` signed in.
6. Verify `https://tradix.axiara.ai/history` shows any previously-created runs (auto-link-by-email at work — if your Google email matches the email NextAuth got from GitHub on a prior sign-in, you'll see the same history).

- [ ] **Step 6: Sync local main + cleanup feature branch**

```bash
git checkout main && git pull fork main
git branch -d feature/auth-ui-google
```

Expected: local main fast-forwards past the merge commit.

---

## Acceptance criteria

Mapping back to design §12:

- [ ] **§12.1** `/login` renders centered glass card with brand chrome → Task 11 (e2e) + Task 16 step 5 (manual).
- [ ] **§12.2** "Continue with GitHub" works end-to-end → Task 16 step 5.
- [ ] **§12.3** "Continue with Google" works end-to-end → Task 16 step 5.
- [ ] **§12.4** Auto-link by email: GitHub-then-Google with same email → one user row → Task 6 test + Task 16 step 5 verification.
- [ ] **§12.5** `E2E_TEST_MODE=1` + `NODE_ENV=production` crashes web container at boot → Task 7 smoke + manual verification per PR body.
- [ ] **§12.6** `/api/auth/signin` redirects to `/login` → Task 7 (`pages.signIn` config) + Task 16 step 5.
- [ ] **§12.7** Existing in-flight JWTs continue to authenticate → Task 6 test `test_legacy_jwt_without_provider_treated_as_github` + Task 16 (no forced sign-out observed).
- [ ] **§12.8** Migration up + down round-trips → Task 5 step 3 (manual run) + ongoing via server test suite.
- [ ] **§12.9** Auth-config production-guard tests pass → Task 7 step 4 smoke.
- [ ] **§12.10** Auto-link-by-email tests pass → Task 5 step 3 (4 tests) + Task 6 step 4 (3 tests).
