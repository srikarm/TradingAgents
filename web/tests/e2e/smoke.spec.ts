import { test, expect } from "@playwright/test";

test("sign in via credentials provider and read a seeded run", async ({ page }) => {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill("e2e-user");
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page).toHaveURL(/\/history/);
  await expect(page.getByText("NVDA")).toBeVisible();

  await page.getByText("NVDA").click();
  await expect(page.getByRole("heading", { name: /NVDA · 2024-05-10/i })).toBeVisible();
  await expect(page.getByText("market — NVDA")).toBeVisible();
});

test("launch a run and observe queued status on live monitor", async ({ page }) => {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill("e2e-user");
  await page.getByRole("button", { name: /sign in/i }).click();

  await page.goto("/launch");
  await page.getByRole("textbox", { name: /ticker/i }).fill("TSLA");
  await page.getByLabel("Trade date").fill("2024-05-10");
  await page.getByRole("button", { name: /^launch$/i }).click();

  // We should be redirected to /live/<run_id>
  await page.waitForURL(/\/live\/[a-f0-9-]+/);
  await expect(page.getByRole("heading", { name: /TSLA · 2024-05-10/i })).toBeVisible();
  // Status pill renders one of the expected states
  await expect(page.locator("strong").filter({ hasText: /QUEUED|RUNNING|SUCCEEDED|FAILED/ }).first()).toBeVisible();
});
