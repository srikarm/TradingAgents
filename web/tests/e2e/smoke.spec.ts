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
