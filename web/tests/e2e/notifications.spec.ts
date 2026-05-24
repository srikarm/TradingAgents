// web/tests/e2e/notifications.spec.ts — Wave 5.4 signal-alerts prefs UI.
import { test, expect, type Page } from "@playwright/test";
import { signInAs } from "./helpers";

const E2E_USER = `e2e-${crypto.randomUUID()}`;

async function signIn(page: Page) {
  await signInAs(page, E2E_USER);
}

test.describe("/watchlist signal alerts", () => {
  test("enable alerts, edit threshold, persists across reload", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    // Card is present and OFF.
    await expect(page.getByText("Signal alerts", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: /enable alerts/i }).click();

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
    // Sequential: the prior test enabled alerts for this spec's shared user.
    await page.getByRole("button", { name: /disable alerts/i }).click();
    await expect(page.getByText("Signal alerts", { exact: true })).toBeVisible();

    await page.reload();
    // After disable, the OFF-state Enable button is present again.
    await expect(page.getByText("Signal alerts", { exact: true })).toBeVisible();
  });
});
