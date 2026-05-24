import { type Page, expect } from "@playwright/test";

// Shared e2e sign-in via the E2E_TEST_MODE credentials provider. Each spec
// passes its own per-run unique githubId so specs don't pollute each other's
// state (a fresh githubId resolves to a fresh user — empty watchlist, monitor
// + notifications OFF), and re-runs don't inherit stale DB state.
export async function signInAs(page: Page, githubId: string): Promise<void> {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill(githubId);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/history/);
}
