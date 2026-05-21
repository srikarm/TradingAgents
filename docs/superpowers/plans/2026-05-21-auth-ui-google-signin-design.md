# Design: Auth UI redesign + Google sign-in (Wave 4 item 1)

**Date:** 2026-05-21
**Status:** Approved (design) — implementation plan to follow
**Owner:** erikgunawans
**Related:** First item of Wave 4 (UX improvements that build on the production deploy shipped via PRs #19/#20/#21). Items 2-3 (real-time analysis opt-in, technical chart) will be brainstormed separately.

---

## 1. Context

The TradingAgents dashboard at `https://tradix.axiara.ai` currently authenticates users via NextAuth (Auth.js v5) with a single OAuth provider — GitHub. The sign-in surface is NextAuth's default unstyled `/api/auth/signin` page; clicking the GitHub button is the only path in. The user wants:

- A second provider — Google — so people without GitHub accounts can sign in.
- A "proper" sign-in page that visually matches the existing Axiara brand (Tailwind + design tokens established in PR #16): pure-black background, ambient red+blue radial gradient, glass surfaces, brand-red slash-mark logo, Inter + JetBrains Mono fonts, eyebrow labels.
- The security gap repeatedly flagged in memory (the `E2E_TEST_MODE=1` env-var-gated credentials backdoor in `web/lib/auth.ts:15-27`) hardened so misconfiguration in production hard-fails the server rather than silently opening auth.

## 2. Goals

- `https://tradix.axiara.ai/login` renders a custom sign-in card that matches Axiara brand chrome.
- Both GitHub and Google sign-in flows work end-to-end and land the user on `/history`.
- A user who signs in with GitHub once, then later signs in with Google using the same email, gets the *same* user record (auto-linked by verified email).
- Setting `E2E_TEST_MODE=1` while `NODE_ENV=production` causes the web container to fail at boot with an explicit error message — the credentials backdoor cannot leak into production via env-var drift.
- The implementation respects the existing JWT-session strategy (no NextAuth database adapter introduced); user persistence stays in the existing Postgres `users` table managed by the FastAPI backend.

## 3. Non-goals

- Third-party providers beyond GitHub + Google (Microsoft, Apple, email magic link). Additive later.
- Marketing/landing-page surface above the sign-in card. The chosen layout is unified + minimal.
- A "Link another account" settings UI for users who explicitly want to merge accounts that have different emails. Out of scope; rare for our user shape.
- Password / username-credentials auth for end users. The dev-only credentials provider stays (with the new hardening guard), but is not exposed to end users.
- Avatar fetching or profile-detail expansion in the session. The session continues to surface just `email` + `providerId`.
- Replacing the existing JWT strategy with a NextAuth database adapter. The existing `session: { strategy: "jwt" }` is preserved.

## 4. Architecture

Three logical changes, no new services:

1. **`web/lib/auth.ts`** — add Google provider, add a production guard around the E2E credentials provider, update JWT/session callbacks to handle both `profile.id` (GitHub numeric) and `profile.sub` (Google string) and to capture `email` as the canonical cross-provider identity.

2. **New `/login` route in the web container** — custom server-rendered sign-in page using Tailwind + the existing Axiara design tokens. Replaces NextAuth's default `/api/auth/signin` via `pages: { signIn: "/login" }` in the auth config.

3. **Server-side user model** — Alembic migration adds an `email` column (UNIQUE WHERE NOT NULL) and a `google_sub` column to the `users` table; the user-resolution helper in `server/app/auth.py` is updated to find-or-create users by `email` as the primary key (with `github_id` and `google_sub` as secondary lookups).

```
                ┌──────────────────────────────────────────────────┐
   Caddy ──►    │  web (Next.js)                                   │
                │    └─► /login  (new, server-rendered)            │
                │          └─► SignInForm (client component)       │
                │                ├─► ProviderButton "GitHub"       │
                │                └─► ProviderButton "Google"       │
                │    └─► /api/auth/* (NextAuth, modified config)   │
                │                ├─► GitHub provider               │
                │                ├─► Google provider (NEW)         │
                │                └─► Credentials (DEV-ONLY, guarded)│
                │          └─► JWT issued ──signs──► api requests  │
                └──────────────────────────────────────────────────┘
                                                │
                                                ▼
                ┌──────────────────────────────────────────────────┐
                │  api (FastAPI)                                    │
                │    server/app/auth.py: verify JWT, look up user  │
                │    by email (canonical) with provider_id fallback│
                │                                                  │
                │  Postgres `users`:                                │
                │    + email           TEXT UNIQUE (new)            │
                │    + google_sub      TEXT UNIQUE (new)            │
                │    + github_id       TEXT (existing)              │
                └──────────────────────────────────────────────────┘
```

## 5. File structure

| File | Action | Responsibility |
|---|---|---|
| `web/lib/auth.ts` | modify | NextAuth config — providers, callbacks, pages, E2E guard |
| `web/app/login/page.tsx` | create | Server component — layout shell + auth-state redirect-if-signed-in |
| `web/app/login/SignInForm.tsx` | create | Client component — wraps `signIn()` calls and renders error banner |
| `web/components/ProviderButton.tsx` | create | Reusable button — icon + label + provider key |
| `server/alembic/versions/<sha>_users_add_email_google_sub.py` | create | Migration — add `email`, `google_sub`, two partial-unique indexes |
| `server/app/models/user.py` | modify | SQLAlchemy model — add `email` + `google_sub` columns; add `find_or_create_by_identity()` helper. Exact path confirmed during implementation (see §11). |
| `server/app/auth.py` | modify | JWT verifier — accept either `github_id` or `google_sub` claim, look up user by email first then provider_id |
| `scripts/gen-prod-env.sh` | modify | Add `AUTH_GOOGLE_ID` + `AUTH_GOOGLE_SECRET` template placeholders |
| `docs/runbooks/first-boot.md` | modify | Add "create Google OAuth client" step before env-file population |
| `web/app/api/auth/[...nextauth]/route.ts` | none | unchanged — exported handlers from `lib/auth.ts` already cover both providers |

## 6. `web/lib/auth.ts` — concrete shape

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

// Dev-only credentials backdoor. Hard-fails if it ever sees production.
// This is the durable fix for the security concern flagged 13 times in
// the project memory (observations 19708-19994).
if (process.env.E2E_TEST_MODE === "1") {
  if (process.env.NODE_ENV === "production") {
    throw new Error(
      "E2E_TEST_MODE=1 cannot run with NODE_ENV=production. " +
      "This guards the credentials-provider backdoor from leaking via env-var drift."
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
        token.email = user.email ?? token.email;
        (token as { provider?: string }).provider = "e2e";
      }
      return token;
    },
    async session({ session, token }) {
      if (token.sub) {
        const u = session.user as { providerId?: string; githubId?: string };
        u.providerId = token.sub;
        // Legacy alias for code paths that still read githubId. Remove in
        // a later refactor once server/app/auth.py keys exclusively off
        // email + providerId.
        u.githubId = token.sub;
      }
      return session;
    },
  },
  secret,
};

export const { handlers, signIn, signOut, auth } = NextAuth(authConfig);
```

## 7. `/login` page — composition

`web/app/login/page.tsx` (server component):

- Calls `auth()` to check for an existing session. Redirects to `/history` if already signed in.
- Reads `?error=...` and `?callbackUrl=...` from `searchParams`.
- Renders a centered glass card on the ambient-gradient background. Inside the card:
  - 28×28 brand-red gradient slash-mark logo (matches the header logo used elsewhere).
  - Eyebrow label `tradingagents` in JetBrains Mono.
  - Heading "Sign in" (Inter semibold).
  - Subtitle "Continue with your preferred account" (Inter, muted).
  - `<SignInForm callbackUrl={...} error={...} />` containing the two provider buttons.

`web/app/login/SignInForm.tsx` (client component):

- Two `<ProviderButton provider="github" />` + `<ProviderButton provider="google" />`, stacked, full-width.
- If `error` prop is set, shows a small red-bordered error banner above the buttons with a NextAuth-error-code-to-friendly-message mapping (`AccessDenied`, `OAuthAccountNotLinked`, `Configuration`, etc.).
- Each button click calls `signIn(provider, { callbackUrl: callbackUrl ?? "/history" })`.

`web/components/ProviderButton.tsx`:

- Props: `provider: "github" | "google"`, optional `disabled`.
- Renders icon + label inside an outlined button (white-on-dark, subtle hover lift).
- The icon SVGs live inline in the component file (~15 lines total).

## 8. Server-side identity model

### Migration

```python
# server/alembic/versions/<sha>_users_add_email_google_sub.py

def upgrade():
    op.add_column("users", sa.Column("email", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("google_sub", sa.String(64), nullable=True))
    op.create_index(
        "ix_users_email_unique", "users", ["email"],
        unique=True, postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "ix_users_google_sub_unique", "users", ["google_sub"],
        unique=True, postgresql_where=sa.text("google_sub IS NOT NULL"),
    )

def downgrade():
    op.drop_index("ix_users_google_sub_unique", "users")
    op.drop_index("ix_users_email_unique", "users")
    op.drop_column("users", "google_sub")
    op.drop_column("users", "email")
```

Both `email` and `google_sub` are nullable so the migration doesn't break existing rows (the one prod user record currently has only `github_id` set). New sign-ins always populate `email`; existing GitHub sessions will populate it on next sign-in.

### User resolution helper

`server/app/models/user.py` (or wherever the model lives — confirm during implementation):

```python
async def find_or_create_by_identity(
    session: AsyncSession,
    *,
    email: str,
    provider: Literal["github", "google", "e2e"],
    provider_id: str,
) -> User:
    """
    Auto-link by verified email. Returns the user that owns this email,
    creating one if necessary, and ensuring the per-provider id column
    is populated.
    """
    # 1. Look up by email — the canonical key.
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        # 2. Legacy fallback — look up by provider_id (for users created
        #    before the email column existed).
        col = {"github": User.github_id, "google": User.google_sub}.get(provider)
        if col is not None:
            user = await session.scalar(select(User).where(col == provider_id))
        if user is None:
            user = User(email=email)
            session.add(user)
    # 3. Backfill the provider id if missing.
    if provider == "github" and user.github_id is None:
        user.github_id = provider_id
    elif provider == "google" and user.google_sub is None:
        user.google_sub = provider_id
    # 4. Backfill email if missing (legacy user resigning in with a provider).
    if user.email is None:
        user.email = email
    await session.flush()
    return user
```

`server/app/auth.py` (JWT verifier) is updated to read both `email` and `providerId` from the JWT claims and call `find_or_create_by_identity()` instead of the current `find_user_by_github_id()` path. Existing JWTs in flight (signed before the migration) still work — their `email` claim is present (NextAuth surfaces GitHub email today), the verifier just keys off that.

## 9. Configuration changes

### New env vars

```
AUTH_GOOGLE_ID=<from Google Cloud Console OAuth credentials>
AUTH_GOOGLE_SECRET=<from Google Cloud Console OAuth credentials>
```

### `scripts/gen-prod-env.sh`

The "GitHub OAuth" block becomes "OAuth providers":

```
# OAuth providers (paste from each provider's settings page)
AUTH_GITHUB_ID=PASTE_FROM_GITHUB_OAUTH_APP
AUTH_GITHUB_SECRET=PASTE_FROM_GITHUB_OAUTH_APP
AUTH_GOOGLE_ID=PASTE_FROM_GOOGLE_CLOUD_OAUTH_CLIENT
AUTH_GOOGLE_SECRET=PASTE_FROM_GOOGLE_CLOUD_OAUTH_CLIENT
```

### `docs/runbooks/first-boot.md`

New step under "Prerequisites":

> **Google OAuth client**: at https://console.cloud.google.com/apis/credentials, create a new OAuth 2.0 Client ID of type "Web application". Set "Authorized redirect URIs" to `https://tradix.axiara.ai/api/auth/callback/google` (plus `http://localhost:3001/api/auth/callback/google` if you ever want to use Google in dev). Copy the Client ID + Client Secret.

### Live deploy

For the running `tradix.axiara.ai` instance, after merge:

1. Create the Google OAuth client (per runbook).
2. Append `AUTH_GOOGLE_ID=...` and `AUTH_GOOGLE_SECRET=...` to `/etc/tradingagents/env` on the VM.
3. Recreate the web container so it picks up the new env: `sudo docker compose --env-file /etc/tradingagents/env -f docker-compose.yml -f docker-compose.prod.yml up -d --force-recreate web`.

## 10. Testing strategy

| Test | Location | Type |
|---|---|---|
| `auth.ts` throws if `E2E_TEST_MODE=1` && `NODE_ENV=production` | `web/lib/__tests__/auth.test.ts` (new) | Unit |
| `auth.ts` allows E2E credentials provider when not in prod | same | Unit |
| JWT `sub` callback maps `account.provider=google` correctly | same | Unit |
| JWT `sub` callback maps `account.provider=github` correctly | same | Unit |
| `find_or_create_by_identity` creates new user if email unknown | `server/tests/test_user_identity.py` (new) | Unit |
| `find_or_create_by_identity` finds existing user by email and backfills google_sub | same | Unit |
| `find_or_create_by_identity` is idempotent on re-sign-in | same | Unit |
| `/login` redirects to `/history` if already signed in | `web/app/login/__tests__/page.test.tsx` (new) | Component |
| `SignInForm` renders error banner when `?error=AccessDenied` | same | Component |
| Migration up + down round-trips | `server/tests/test_migrations.py` (existing pattern) | Integration |
| End-to-end Google sign-in (against the OAuth app's `localhost` callback) | manual smoke during rollout | Manual |
| End-to-end GitHub sign-in unaffected | manual smoke during rollout | Manual |

The auto-link-by-email behavior gets a dedicated test that signs in as `e@x.com` with provider=github, then with provider=google, and asserts only one user row exists with both `github_id` and `google_sub` populated.

## 11. Open questions

1. **Existing user emails.** The one prod user record (you) currently has `github_id` set but `email` is NULL. After migration, your next sign-in (with either GitHub or Google) will populate `email`. Until then, the legacy `find by github_id` fallback covers the existing session. Confirm we're OK with "next sign-in populates email" rather than a one-shot backfill.

2. **Google OAuth consent screen.** First-time Google sign-in for an "External" OAuth app shows a consent screen. If the OAuth client is set to "Testing" mode (default for new clients), only emails on the test-user list can sign in until verification. Decision: ship with "Testing" mode + a 1-2 person test-user list for now, request app verification later if usage grows.

3. **Server-side JWT verifier file path.** `server/app/auth.py` is the assumed location; confirm during implementation (may live under `server/app/api/auth.py` or `server/app/security.py`). The implementation plan will pin the exact path.

## 12. Acceptance criteria

The implementation is done when all of these are true:

- [ ] `https://tradix.axiara.ai/login` renders the centered glass card with the brand-red slash logo, eyebrow `tradingagents` label, "Sign in" heading, and two stacked provider buttons (GitHub + Google).
- [ ] Clicking "Continue with GitHub" completes the OAuth flow and lands on `/history`.
- [ ] Clicking "Continue with Google" completes the OAuth flow and lands on `/history`.
- [ ] Signing in first with GitHub using email `e@x.com`, then signing out and signing in with Google using the same email, results in ONE user row with both `github_id` and `google_sub` populated. The history visible after the Google sign-in matches the history from the GitHub session.
- [ ] Setting `E2E_TEST_MODE=1` and `NODE_ENV=production` causes the web container to fail at boot with the explicit guard error. Verified locally during implementation; not actually deployed.
- [ ] `/api/auth/signin` (NextAuth's default) redirects to `/login` (because of `pages.signIn`).
- [ ] Existing in-flight JWTs (signed before the migration) continue to authenticate successfully — no forced sign-out.
- [ ] Migration `upgrade()` + `downgrade()` round-trip cleanly in tests.
- [ ] Unit tests for the auth-config production guard pass.
- [ ] Test coverage of the auto-link-by-email behavior passes.
