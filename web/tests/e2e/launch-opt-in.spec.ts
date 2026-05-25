// web/tests/e2e/launch-opt-in.spec.ts
import { test, expect, type Page } from "@playwright/test";

/** Sign in via credentials provider (same pattern as smoke.spec.ts). */
async function signIn(page: Page) {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill("e2e-user");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL(/\/history/);
}

test.describe("launch opt-in", () => {
  test("Watch live checkbox is unchecked by default", async ({ page }) => {
    await signIn(page);
    await page.goto("/launch");
    const checkbox = page.getByRole("checkbox", { name: /Watch live/i });
    await expect(checkbox).toBeVisible();
    await expect(checkbox).not.toBeChecked();
  });

  test("submit with checkbox checked lands on /live/{id}", async ({ page }) => {
    await signIn(page);
    await page.goto("/launch");
    await page.getByRole("textbox", { name: /ticker/i }).fill("BBCA.JK");
    await page.getByLabel("Trade date").fill("2026-05-21");
    await page.getByRole("checkbox", { name: /Watch live/i }).check();
    await page.getByRole("button", { name: /launch/i }).click();
    await expect(page).toHaveURL(/\/live\/[a-f0-9-]+/);
  });

  test("submit with checkbox unchecked lands on /history", async ({ page }) => {
    await signIn(page);
    await page.goto("/launch");
    await page.getByRole("textbox", { name: /ticker/i }).fill("BMRI.JK");
    await page.getByLabel("Trade date").fill("2026-05-21");
    // Leave checkbox unchecked.
    await page.getByRole("button", { name: /launch/i }).click();
    await expect(page).toHaveURL(/\/history(\?|$)/);
  });
});

test.describe("RunsBadge in nav", () => {
  test("hidden when no in-progress runs", async ({ page }) => {
    await signIn(page);
    // Mock the count endpoint at the network layer to avoid worker dependency.
    await page.route("**/runs/active/count", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ count: 0 }),
      })
    );
    await page.goto("/history");
    // The badge link is hidden when count === 0 (returns null).
    await expect(page.getByRole("link", { name: /run.*in progress/i })).toHaveCount(0);
  });

  // These two mock the /runs/active/count HTTP endpoint, but RunsBadge now
  // fetches via a server action (countActiveRunsAction), so the browser never
  // hits that endpoint and the route mock is dead. Skipped until reworked to
  // seed active runs instead of HTTP-mocking. (The count===0 case above still runs.)
  test.skip("visible with correct count + plural label", async ({ page }) => {
    await signIn(page);
    await page.route("**/runs/active/count", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ count: 3 }),
      })
    );
    await page.goto("/history");
    const badge = page.getByRole("link", { name: /3 runs in progress/i });
    await expect(badge).toBeVisible();
    await expect(badge).toHaveAttribute("href", "/history");
    await expect(badge).toContainText("3 runs");
  });

  test.skip("singular label when count is 1", async ({ page }) => {
    await signIn(page);
    await page.route("**/runs/active/count", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ count: 1 }),
      })
    );
    await page.goto("/history");
    const badge = page.getByRole("link", { name: /1 run in progress/i });
    await expect(badge).toContainText("1 run");
  });
});
