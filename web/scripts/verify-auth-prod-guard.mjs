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
