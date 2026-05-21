import { test, expect } from "@playwright/test";

test.describe("/login page", () => {
  test("renders both provider buttons and brand chrome", async ({ page }) => {
    await page.goto("/login");

    await expect(page.locator("h1")).toHaveText("Sign in");
    await expect(page.getByText("tradingagents")).toBeVisible();
    await expect(page.getByText("Continue with your preferred account")).toBeVisible();

    const githubButton = page.getByRole("button", { name: "Continue with GitHub" });
    const googleButton = page.getByRole("button", { name: "Continue with Google" });
    await expect(githubButton).toBeVisible();
    await expect(googleButton).toBeVisible();
  });

  test("shows error banner when ?error=AccessDenied", async ({ page }) => {
    await page.goto("/login?error=AccessDenied");
    // Use .first() — Next.js also injects a role=alert route-announcer element.
    await expect(page.getByRole("alert").first()).toContainText("cancelled or denied");
  });

  test("unknown error code falls back to generic message", async ({ page }) => {
    await page.goto("/login?error=FunkyUnknownCode");
    await expect(page.getByRole("alert").first()).toContainText("FunkyUnknownCode");
  });
});
