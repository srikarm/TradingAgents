import { test, expect } from "@playwright/test";

test("portfolio page renders headings and metric cards", async ({ page }) => {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill("e2e-user");
  await page.getByRole("button", { name: /sign in/i }).click();

  await page.goto("/portfolio");
  await expect(page.getByRole("heading", { name: "Portfolio" })).toBeVisible();
  await expect(page.getByText("Cumulative P&L")).toBeVisible();
  await expect(page.getByText("Win rate")).toBeVisible();
  await expect(page.getByText(/Sharpe/i)).toBeVisible();
  await expect(page.getByText("Max drawdown")).toBeVisible();
});
