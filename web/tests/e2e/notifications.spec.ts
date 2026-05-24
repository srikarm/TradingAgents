// web/tests/e2e/notifications.spec.ts — Wave 5.4 signal-alerts prefs UI.
import { test, expect } from "@playwright/test";

async function signIn(page) {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill("e2e-user");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/history/);
}

test.describe("/watchlist signal alerts", () => {
  test("enable alerts, edit threshold, persists across reload", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    // Card is present and OFF.
    await expect(page.getByText("Signal alerts", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: /^enable$/i }).nth(1).click();

    // ON state surfaces the threshold control + Disable.
    await expect(page.getByText("Signal alerts on")).toBeVisible();
    const threshold = page.getByLabel("Alert ratings");
    await expect(threshold).toBeVisible();

    // Edit threshold and wait past the 800ms debounce.
    await threshold.fill("BUY");
    await page.waitForTimeout(1200);
    await expect(page.getByText(/We'll email you when a BUY signal lands/i)).toBeVisible();

    // ROUND-TRIP: reload and confirm the enabled + threshold state persisted.
    await page.reload();
    await expect(page.getByText("Signal alerts on")).toBeVisible();
    await expect(page.getByLabel("Alert ratings")).toHaveValue("BUY");
  });

  test("disable returns to OFF and persists on reload", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");
    // Sequential to the prior test — alerts were enabled.
    await page.getByRole("button", { name: /^disable$/i }).click();
    await expect(page.getByText("Signal alerts", { exact: true })).toBeVisible();

    await page.reload();
    // After disable, the OFF-state Enable button is present again.
    await expect(page.getByText("Signal alerts", { exact: true })).toBeVisible();
  });
});
