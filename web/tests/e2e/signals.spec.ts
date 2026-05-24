import { test, expect, type Page } from "@playwright/test";
import { signInAs } from "./helpers";

const E2E_USER = `e2e-${crypto.randomUUID()}`;

async function signIn(page: Page) {
  await signInAs(page, E2E_USER);
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
    // Monitor "Enable" is disabled until the watchlist has a ticker.
    await page.getByLabel("Ticker").fill("SIG");
    await page.getByRole("button", { name: /^add$/i }).click();
    await expect(page.getByRole("link", { name: "SIG" })).toBeVisible();
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
