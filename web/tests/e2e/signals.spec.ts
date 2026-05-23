import { test, expect } from "@playwright/test";

async function signIn(page) {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill("e2e-user");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/history/);
}

test.describe("/signals", () => {
  test("monitor-off empty state renders", async ({ page }) => {
    await signIn(page);
    // Disable monitor first (idempotent, in case previous tests left it on).
    await page.goto("/watchlist");
    const disable = page.getByRole("button", { name: /^disable$/i });
    if (await disable.isVisible().catch(() => false)) {
      await disable.click();
    }
    await page.goto("/signals");
    await expect(page.getByRole("heading", { name: /Daily Monitor is off/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /Go to Watchlist/i })).toBeVisible();
  });

  test("no-signals-yet empty state renders after enabling", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");
    await page.getByRole("button", { name: /^enable$/i }).click();
    await page.goto("/signals");
    await expect(page.getByRole("heading", { name: /No signals yet/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /Manage Monitor/i })).toBeVisible();
  });

  test("Signals nav item links to /signals", async ({ page }) => {
    await signIn(page);
    await page.getByRole("link", { name: /signals/i }).click();
    await expect(page).toHaveURL(/\/signals/);
  });

  test.skip("Signal card → /history/[runId]", async ({ page }) => {
    // Requires seeded triggered_by='monitor' run; deferred to manual smoke post-merge.
  });
});
