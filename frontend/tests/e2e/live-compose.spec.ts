import { expect, test } from "@playwright/test";

test("runs the live compose onboarding, configures SQLite, and asks a question", async ({ page }) => {
  test.skip(!process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD is required for live compose smoke");

  await page.goto("/");
  await page.getByLabel("Admin email").fill(process.env.ADMIN_EMAIL ?? "admin@dataclaw.local");
  await page.getByLabel("Admin password").fill(process.env.ADMIN_PASSWORD!);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("tab", { name: /Gateway/ })).toBeVisible();
  await expect(page.getByText("Empty", { exact: true })).toBeVisible();

  await page.locator(".connector-row", { hasText: "SQLite" }).getByRole("button", { name: "Configure" }).click();
  await page.getByRole("button", { name: "Test connection" }).click();
  await expect(page.getByText(/Connection succeeded/)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Save and sync" }).click();

  await expect(page.locator(".kb-group strong").filter({ hasText: /SQLite/ })).toBeVisible({ timeout: 30_000 });

  await page.getByRole("tab", { name: /Editor/ }).click();
  await page.getByRole("button", { name: /Show me daily revenue/ }).click();
  await page.getByRole("textbox", { name: "Ask about your data" }).press("Enter");
  await expect(page.getByText(/openai|deterministic_local/)).toBeVisible({ timeout: 120_000 });
});
