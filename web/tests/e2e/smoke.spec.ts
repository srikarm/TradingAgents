import { test, expect } from "@playwright/test";
import { signInAs } from "./helpers";

test("sign in via credentials provider and read a seeded run", async ({ page }) => {
  await signInAs(page, "e2e-user"); // seeded fixture user; waits for /history

  await expect(page.getByText("NVDA")).toBeVisible();

  await page.getByText("NVDA").first().click();
  await expect(page.getByRole("heading", { name: "NVDA", exact: true })).toBeVisible();
  await expect(page.getByText("2024-05-10")).toBeVisible();
  await expect(page.getByText("Market Analysis — NVDA")).toBeVisible();
});

test("launch a run and observe queued status on live monitor", async ({ page }) => {
  await signInAs(page, "e2e-user"); // waits for /history before navigating

  await page.goto("/launch");
  await page.getByRole("textbox", { name: /ticker/i }).fill("TSLA");
  await page.getByLabel("Trade date").fill("2024-05-10");
  await page.getByRole("button", { name: /^launch$/i }).click();

  // We should be redirected to /live/<run_id>
  await page.waitForURL(/\/live\/[a-f0-9-]+/);
  await expect(page.getByRole("heading", { name: "TSLA", exact: true })).toBeVisible();
  // Status pill renders one of the expected states
  await expect(page.locator("strong").filter({ hasText: /QUEUED|RUNNING|SUCCEEDED|FAILED/ }).first()).toBeVisible();
});
