// web/tests/e2e/ticker-chart.spec.ts
import { test, expect } from "@playwright/test";

async function signIn(page) {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill("e2e-user");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/history/);
}

test.describe("/portfolio/[ticker] chart", () => {
  test("renders TickerChartWorkspace with both canvases", async ({ page }) => {
    await signIn(page);
    await page.goto("/history");
    await page.getByText("NVDA").first().click();
    // From /history NVDA row we end up at /history/{runId}; navigate to portfolio explicitly.
    await page.goto("/portfolio/NVDA");

    // Workspace container is present with our data-testid.
    const workspace = page.getByTestId("ticker-chart-workspace");
    await expect(workspace).toBeVisible();

    // Two <canvas> elements: one for the main chart (price+volume), one for RSI.
    await expect(workspace.locator("canvas")).toHaveCount(
      2,
      { timeout: 5000 },
    );

    // Header shows the ticker and indicator legend.
    await expect(workspace.getByText("NVDA")).toBeVisible();
    await expect(workspace.getByText(/sma\(20,50\)/i)).toBeVisible();
    await expect(workspace.getByText(/rsi\(14\)/i)).toBeVisible();
  });

  test("Daily / Hourly toggle updates URL searchParams", async ({ page }) => {
    await signIn(page);
    await page.goto("/portfolio/NVDA");

    // Default = 1d. Click 1H button.
    const hourlyTab = page.getByRole("tab", { name: "1H" });
    await hourlyTab.click();

    await expect(page).toHaveURL(/\?interval=1h/);
    await expect(hourlyTab).toHaveAttribute("aria-selected", "true");

    // Click back to 1D.
    await page.getByRole("tab", { name: "1D" }).click();
    await expect(page).not.toHaveURL(/interval=1h/);
  });

  test("decisions render below the chart in the timeline", async ({ page }) => {
    await signIn(page);
    await page.goto("/portfolio/NVDA");

    // The Decisions section heading.
    await expect(page.getByRole("heading", { name: /^Decisions$/i })).toBeVisible();

    // At least one row in the timeline table for the seeded NVDA fixture.
    const table = page.locator("table").last();
    await expect(table).toBeVisible();
    await expect(table.locator("tbody tr")).not.toHaveCount(0);
  });
});
