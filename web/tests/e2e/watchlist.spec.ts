import { test, expect } from "@playwright/test";

async function signIn(page) {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill("e2e-user");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/history/);
}

test.describe("/watchlist", () => {
  test("empty state renders for a new user", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");
    await expect(page.getByRole("heading", { name: "Watchlist" })).toBeVisible();
    await expect(page.getByText("Add a ticker above to start watching.")).toBeVisible();
  });

  test("add a ticker via QuickAddForm; row appears", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    await page.getByLabel("Ticker").fill("AAPL");
    await page.getByLabel("Notes").fill("tracking earnings");
    await page.getByRole("button", { name: /^add$/i }).click();

    // Wait for router.refresh() to repaint the table.
    await expect(page.getByRole("link", { name: "AAPL" })).toBeVisible();
    await expect(page.getByText("tracking earnings")).toBeVisible();
  });

  test("duplicate add shows inline error", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    // Add first instance (clean state assumed from prior test or fresh DB).
    await page.getByLabel("Ticker").fill("DUPE");
    await page.getByRole("button", { name: /^add$/i }).click();
    await expect(page.getByRole("link", { name: "DUPE" })).toBeVisible();

    // Try to add again.
    await page.getByLabel("Ticker").fill("DUPE");
    await page.getByRole("button", { name: /^add$/i }).click();
    await expect(page.getByRole("alert")).toContainText(/already on your watchlist/i);
  });

  test("lowercase ticker is auto-uppercased on input", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    const tickerInput = page.getByLabel("Ticker");
    await tickerInput.fill("nvda");
    await expect(tickerInput).toHaveValue("NVDA");
  });

  test("edit notes inline; persists after reload", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    // Seed a row.
    await page.getByLabel("Ticker").fill("MSFT");
    await page.getByRole("button", { name: /^add$/i }).click();
    await expect(page.getByRole("link", { name: "MSFT" })).toBeVisible();

    // Click the notes cell to start editing.
    const notesCell = page.getByText("Click to add notes").first();
    await notesCell.click();

    const textarea = page.locator("textarea").first();
    await textarea.fill("monitoring AI rumors");
    await textarea.press("Enter");

    await expect(page.getByText("monitoring AI rumors")).toBeVisible();

    // Reload and confirm persistence.
    await page.reload();
    await expect(page.getByText("monitoring AI rumors")).toBeVisible();
  });

  test("remove via modal confirm; row disappears", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    // Seed a row.
    await page.getByLabel("Ticker").fill("TSLA");
    await page.getByRole("button", { name: /^add$/i }).click();
    await expect(page.getByRole("link", { name: "TSLA" })).toBeVisible();

    await page.getByRole("button", { name: /Remove TSLA from watchlist/i }).click();
    await expect(page.getByText("Remove from watchlist?")).toBeVisible();
    await page.getByRole("button", { name: /^remove$/i }).click();

    await expect(page.getByRole("link", { name: "TSLA" })).not.toBeVisible();
  });

  test("clicking a ticker navigates to /portfolio/[ticker]", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    // Seed a row.
    await page.getByLabel("Ticker").fill("GOOG");
    await page.getByRole("button", { name: /^add$/i }).click();
    await expect(page.getByRole("link", { name: "GOOG" })).toBeVisible();

    await page.getByRole("link", { name: "GOOG" }).click();
    await expect(page).toHaveURL(/\/portfolio\/GOOG/);
  });
});
