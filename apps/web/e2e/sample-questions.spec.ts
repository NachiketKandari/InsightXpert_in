import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers/auth";

// The sample-questions modal is opened via the user-menu dropdown.
// Question items are <div> elements (not <button>) — we locate them via role=dialog
// and filter on the section structure.

test.describe("sample-questions modal", () => {
  /**
   * Prerequisite: the bundled DB must have `sample_questions` populated
   * (status = "ok" or "fallback"). Run the seed-bundled-profiles.py operator
   * script before this suite, or set E2E_HAS_SAMPLE_QUESTIONS=1 to skip the
   * regenerate auto-fire path.
   *
   * If no profile data exists the modal auto-fires a regenerate on open, which
   * means the dialog will show skeleton rows (pending state) rather than 9
   * question items. In that environment test 1 will fail but test 2 will pass.
   */

  test("sample questions modal renders 3 categories and 9 questions from profile", async ({
    page,
  }) => {
    test.skip(
      !process.env.E2E_HAS_SAMPLE_QUESTIONS,
      "Set E2E_HAS_SAMPLE_QUESTIONS=1 with a seeded bundled DB profile (status=ok or fallback)",
    );

    await loginAsAdmin(page);
    await page.goto("/");

    // Open the user-menu dropdown (the avatar/initials button at the top of the sidebar)
    await page.getByRole("button", { name: /AI|admin/i }).first().click();

    // Click "Sample Questions" in the dropdown
    await page.getByRole("menuitem", { name: /sample questions/i }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // The title should read "Sample Questions" (not the pending state title)
    await expect(dialog.getByText("Sample Questions")).toBeVisible({ timeout: 10_000 });

    // Three category sections
    const sections = dialog.locator("section");
    await expect(sections).toHaveCount(3);

    // Nine clickable question rows (div elements with cursor-pointer inside each section)
    const questionRows = dialog.locator("section .cursor-pointer");
    await expect(questionRows).toHaveCount(9);

    // Click the first question — it should populate the chat composer
    const first = questionRows.first();
    const text = (await first.locator("span.flex-1").innerText()).trim();
    await first.click();

    // The dialog closes and the textarea is populated with the selected question
    await expect(dialog).not.toBeVisible();
    const textarea = page.locator("textarea");
    await expect(textarea).toHaveValue(text, { timeout: 5_000 });
  });

  test("opening modal with no profile triggers pending/generating state", async ({
    page,
  }) => {
    await loginAsAdmin(page);
    await page.goto("/");

    // Open the user-menu dropdown
    await page.getByRole("button", { name: /AI|admin/i }).first().click();

    // Click "Sample Questions" in the dropdown
    await page.getByRole("menuitem", { name: /sample questions/i }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // The modal either shows the pending title (when auto-fire triggers regenerate)
    // or the final questions. Either way the dialog must be visible and contain
    // the Regenerate button (title attribute: "Regenerate sample questions").
    const regenBtn = dialog.getByRole("button", { name: /regenerate/i });
    await expect(regenBtn).toBeVisible({ timeout: 10_000 });

    // Click Regenerate when it is enabled (i.e. not already in pending state)
    // If already in pending state (auto-fired), the button is disabled — just
    // assert the pending header text is visible instead.
    const isDisabled = await regenBtn.isDisabled();
    if (isDisabled) {
      await expect(dialog.getByText(/Generating starter questions/i)).toBeVisible();
    } else {
      await regenBtn.click();
      await expect(dialog.getByText(/Generating starter questions/i)).toBeVisible();
    }
  });
});
