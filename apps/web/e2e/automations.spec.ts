import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers/auth";

const FLAG_ON = process.env.NEXT_PUBLIC_AUTOMATIONS_ENABLED === "true";

test.describe("automations", () => {
  test.describe("with feature flag on", () => {
    test.skip(!FLAG_ON, "NEXT_PUBLIC_AUTOMATIONS_ENABLED is not 'true'");

    test.beforeEach(async ({ page }) => {
      await loginAsAdmin(page);
    });

    test("renders the list page with a heading", async ({ page }) => {
      await page.goto("/automations");
      await expect(
        page.getByRole("heading", { name: /automations/i }).first(),
      ).toBeVisible();
    });

    test("opens the create dialog and submit is disabled with empty fields", async ({
      page,
    }) => {
      await page.goto("/automations");
      await page
        .getByRole("button", { name: /new automation/i })
        .first()
        .click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      const submit = dialog.getByRole("button", {
        name: /create automation/i,
      });
      await expect(submit).toBeDisabled();
    });
  });

  test("404s when feature flag is off", async ({ page }) => {
    test.skip(FLAG_ON, "Flag is on in this environment");
    const res = await page.goto("/automations");
    expect(res?.status()).toBe(404);
  });
});
