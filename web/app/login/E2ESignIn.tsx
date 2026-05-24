// web/app/login/E2ESignIn.tsx
// Test-only credentials sign-in form. Rendered on /login ONLY when the server
// has E2E_TEST_MODE=1 (see login/page.tsx) — which web/lib/auth.ts hard-fails
// under NODE_ENV=production, so this can never appear in prod. It drives the
// E2E credentials provider via next-auth/react's signIn (CSRF handled for us),
// giving the Playwright suite a reachable login after pages.signIn="/login"
// took the default credentials form away.
"use client";

import { signIn } from "next-auth/react";
import { useState } from "react";

export default function E2ESignIn({ callbackUrl }: { callbackUrl?: string }) {
  const [githubId, setGithubId] = useState("");

  return (
    <form
      className="mt-4 space-y-2 border-t border-white/[0.06] pt-4 text-left"
      onSubmit={(e) => {
        e.preventDefault();
        void signIn("credentials", { githubId, callbackUrl: callbackUrl ?? "/history" });
      }}
    >
      <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-fg-muted">
        E2E test sign-in
      </p>
      <input
        aria-label="GitHub ID"
        name="githubId"
        value={githubId}
        onChange={(e) => setGithubId(e.target.value)}
        className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-fg-primary"
      />
      <button
        type="submit"
        className="w-full rounded-lg border border-brand/40 bg-brand/10 px-3 py-2 text-sm font-medium text-brand transition hover:bg-brand/15"
      >
        Sign in
      </button>
    </form>
  );
}
