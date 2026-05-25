import { test, expect } from "@playwright/test";
import { signInAs } from "./helpers";

test("portfolio page renders headings and metric cards", async ({ page }) => {
  await signInAs(page, "e2e-user"); // seeded fixture user; waits for /history

  await page.goto("/portfolio");
  await expect(page.getByRole("heading", { name: "Portfolio" })).toBeVisible();
  // Each label can appear on both a metric card and a chart axis/legend, so
  // match the first occurrence rather than asserting a single match.
  await expect(page.getByText("Cumulative P&L").first()).toBeVisible();
  await expect(page.getByText("Win rate").first()).toBeVisible();
  await expect(page.getByText(/Sharpe/i).first()).toBeVisible();
  await expect(page.getByText("Max drawdown").first()).toBeVisible();
});
