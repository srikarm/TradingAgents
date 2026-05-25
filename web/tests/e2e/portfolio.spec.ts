import { test, expect } from "@playwright/test";
import { signInAs } from "./helpers";

test("portfolio page renders headings and metric cards", async ({ page }) => {
  await signInAs(page, "e2e-user"); // seeded fixture user; waits for /history

  await page.goto("/portfolio");
  await expect(page.getByRole("heading", { name: "Portfolio" })).toBeVisible();
  await expect(page.getByText("Cumulative P&L")).toBeVisible();
  await expect(page.getByText("Win rate")).toBeVisible();
  await expect(page.getByText(/Sharpe/i)).toBeVisible();
  await expect(page.getByText("Max drawdown")).toBeVisible();
});
