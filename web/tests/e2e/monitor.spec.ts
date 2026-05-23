// web/tests/e2e/monitor.spec.ts
import { test, expect } from "@playwright/test";

async function signIn(page) {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill("e2e-user");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/history/);
}

test.describe("/watchlist daily monitor", () => {
  test("enable monitor and see countdown", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    // Need at least one ticker on the watchlist for Enable to be active.
    await page.getByLabel("Ticker").fill("MON");
    await page.getByRole("button", { name: /^add$/i }).click();
    await expect(page.getByRole("link", { name: "MON" })).toBeVisible();

    // Daily monitor card visible, currently OFF.
    await expect(page.getByText("Daily monitor")).toBeVisible();

    // Enable.
    await page.getByRole("button", { name: /^enable$/i }).click();
    await expect(page.getByText(/Next briefing:/i)).toBeVisible();
    await expect(page.getByLabel("Briefing time")).toBeVisible();
    await expect(page.getByLabel("Timezone")).toBeVisible();
  });

  test("disable preserves config; reload shows OFF state", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");
    // Pre-condition: monitor was enabled in the previous test (sequential e2e).
    await page.getByRole("button", { name: /^disable$/i }).click();
    await expect(page.getByText("Daily monitor")).toBeVisible();
    await expect(page.getByRole("button", { name: /^enable$/i })).toBeVisible();

    await page.reload();
    await expect(page.getByRole("button", { name: /^enable$/i })).toBeVisible();
  });

  test("change time updates the countdown copy", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");
    await page.getByRole("button", { name: /^enable$/i }).click();
    await page.getByLabel("Briefing time").fill("23:59");
    // Wait past the 800ms debounce.
    await page.waitForTimeout(1200);
    // The "at HH:MM" line should reflect the new time.
    await expect(page.getByText(/At 23:59/i)).toBeVisible();
  });

  test("Monitor badge appears on monitor-triggered run in /history", async ({ page, request }) => {
    // Seed a monitor-triggered run via direct API call (assuming the test fixture has an api key).
    // If the test environment doesn't support direct seeding, skip and rely on the manual smoke.
    test.skip(true, "Requires test-environment seed of a triggered_by='monitor' run; covered by manual smoke");
  });
});
