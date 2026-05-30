import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers/auth";

// The chat input placeholder matches once a database is loaded/selected.
const CHAT_PLACEHOLDER = /Ask anything about/i;

test.describe("share-chat", () => {
  test("bundled DB → create → copy → incognito loads → revoke → 404", async ({
    page,
    browser,
  }) => {
    test.setTimeout(60000);
    await loginAsAdmin(page);
    await page.goto("/");

    // The DatabasePickerPanel auto-selects the first bundled DB on load.
    // Fill and submit a question from the WelcomeScreen textarea.
    const textarea = page.getByPlaceholder(CHAT_PLACEHOLDER);
    await expect(textarea).toBeVisible();
    await textarea.fill("How many rows are in the first table?");
    await page.keyboard.press("Enter");

    // After sending, the share-open-btn appears only once a conversationId
    // exists (i.e. the first message round-trip is underway). Wait for it.
    const shareOpenBtn = page.getByTestId("share-open-btn");
    await expect(shareOpenBtn).toBeVisible({ timeout: 30_000 });
    await expect(shareOpenBtn).toBeEnabled({ timeout: 45_000 });

    // Open the share dialog and create a link.
    await shareOpenBtn.click();
    const createBtn = page.getByTestId("share-create-btn");
    await expect(createBtn).toBeVisible();
    await createBtn.click();

    // Wait for the share URL to appear.
    const urlInput = page.getByTestId("share-url-input");
    await expect(urlInput).toBeVisible({ timeout: 10_000 });
    const shareUrl = await urlInput.inputValue();
    expect(shareUrl).toMatch(/\/share\/[A-Za-z0-9_-]+$/);

    // Verify the share page is accessible in an incognito context.
    const ctx = await browser.newContext();
    const anonPage = await ctx.newPage();
    await anonPage.goto(shareUrl);
    await expect(anonPage.getByTestId("share-page")).toBeVisible({ timeout: 15_000 });
    // The chat input must NOT be present on the read-only share view.
    await expect(anonPage.getByPlaceholder(CHAT_PLACEHOLDER)).toHaveCount(0);
    await ctx.close();

    // Revoke the share link.
    const revokeBtn = page.getByTestId("share-revoke-btn");
    await expect(revokeBtn).toBeVisible();
    await revokeBtn.click();

    // Wait for the share dialog to transition back to the "Create share link" state
    // (which confirms the delete mutation completed and the state was refetched).
    const createBtnAfterRevoke = page.getByTestId("share-create-btn");
    await expect(createBtnAfterRevoke).toBeVisible({ timeout: 15_000 });

    // Re-open the dialog (it may close after revoke) and confirm the URL is gone.
    // Then verify the previously-shared URL now returns 404.
    const ctx2 = await browser.newContext();
    const anonPage2 = await ctx2.newPage();
    await anonPage2.goto(shareUrl);
    await expect(anonPage2.getByTestId("share-not-found")).toBeVisible({ timeout: 15_000 });
    await ctx2.close();
  });

  test("postgres-bound chat shows refusal in dialog", async ({ page }) => {
    test.skip(
      !process.env.E2E_HAS_POSTGRES_DB,
      "Set E2E_HAS_POSTGRES_DB=1 with a seeded postgres conversation",
    );
    await loginAsAdmin(page);
    await page.goto(`/?conversation=${process.env.E2E_POSTGRES_CONVERSATION_ID}`);
    await page.getByTestId("share-open-btn").click();
    await expect(page.getByTestId("share-postgres-block")).toBeVisible();
    await expect(page.getByTestId("share-create-btn")).toBeDisabled();
  });
});
