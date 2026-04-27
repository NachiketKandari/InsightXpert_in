import { Page } from "@playwright/test";

/**
 * Logs a user in via the /login form and waits for redirect away from /login.
 *
 * The login page uses labelled inputs (id+htmlFor) for Email and Password,
 * and a "Sign in" submit button. We target by label/role for resilience.
 */
export async function loginAs(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

/**
 * Bootstrap admin credentials seeded by the API on first boot.
 */
export async function loginAsAdmin(page: Page): Promise<void> {
  await loginAs(page, "admin@insightxpert.ai", "admin123");
}
