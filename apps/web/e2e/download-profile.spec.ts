import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers/auth";

test.describe("download database profile (.xlsx)", () => {
  test("downloads xlsx with overview + per-table sheets for a profiled database", async ({
    page,
  }) => {
    /**
     * This test requires at least one database with a completed profile.
     * Seed with `seed-bundled-profiles.py` or ensure a profiled DB exists.
     * Set E2E_HAS_PROFILED_DB=1 to run.
     */
    test.skip(
      !process.env.E2E_HAS_PROFILED_DB,
      "Set E2E_HAS_PROFILED_DB=1 with a seeded bundled DB profile",
    );

    await loginAsAdmin(page);
    await page.goto("/databases");

    // Find a card that says "Profiled" — has a completed profile
    const cards = page.locator("h3.font-mono");
    const count = await cards.count();
    let dbId = "";
    let openLink: ReturnType<typeof page.getByRole> | null = null;

    for (let i = 0; i < count; i++) {
      const h3 = cards.nth(i);
      const card = h3.locator("..").locator(".."); // .flex.flex-col → .rounded-lg
      if (await card.locator("text=Profiled").isVisible().catch(() => false)) {
        dbId = (await h3.innerText()).trim();
        openLink = card.getByRole("link", { name: "Open" });
        break;
      }
    }

    if (!openLink) {
      test.skip(true, "No profiled databases found");
      return;
    }

    // Navigate into the database detail page
    await openLink.click();
    await page.waitForURL(new RegExp(`/databases/${encodeURIComponent(dbId)}$`));

    // The download button should be visible (only when profile is loaded)
    const downloadBtn = page.getByRole("button", { name: /download profile/i });
    await expect(downloadBtn).toBeVisible({ timeout: 15_000 });

    // Initiate the download and capture it
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      downloadBtn.click(),
    ]);

    // Verify filename
    expect(download.suggestedFilename()).toBe(`${dbId}_profile.xlsx`);

    // Save to a temp path so we can read and verify the workbook contents
    const filePath = await download.path();
    expect(filePath).toBeTruthy();

    // Read the xlsx using the same SheetJS lib (available server-side via Node)
    const XLSX = await import("xlsx");
    const wb = XLSX.readFile(filePath!);

    // Verify sheet count: _Overview + one per table
    const sheetNames = wb.SheetNames;
    expect(sheetNames.length).toBeGreaterThanOrEqual(2); // at least _Overview + 1 table
    expect(sheetNames[0]).toBe("_Overview");

    // Verify _Overview has expected columns
    const overviewJson: Record<string, unknown>[] = XLSX.utils.sheet_to_json(
      wb.Sheets["_Overview"],
    );
    expect(overviewJson.length).toBeGreaterThanOrEqual(1);
    const overviewHeaders = Object.keys(overviewJson[0]);
    expect(overviewHeaders).toContain("Table");
    expect(overviewHeaders).toContain("Row Count");
    expect(overviewHeaders).toContain("Column Count");
    expect(overviewHeaders).toContain("Description");

    // Verify each table sheet has column-profile headers
    const expectedHeaders = [
      "Column",
      "Type",
      "Count",
      "Null Count",
      "Distinct Count",
      "Min",
      "Max",
      "Short Summary",
      "Long Summary",
      "BIRD Summary",
      "Semantic Hint",
      "Enum Labels",
      "Aliases",
      "Symbolic",
      "Numbered Group",
      "FK Alias",
      "Type Mismatch",
      "Sample Values",
    ];

    for (let i = 1; i < sheetNames.length; i++) {
      const sheetJson: Record<string, unknown>[] = XLSX.utils.sheet_to_json(
        wb.Sheets[sheetNames[i]],
      );
      if (sheetJson.length === 0) continue; // skip empty sheets (edge case)
      const headers = Object.keys(sheetJson[0]);
      for (const h of expectedHeaders) {
        expect(headers).toContain(h);
      }
    }
  });

  test("download button is absent when no profile exists", async ({
    page,
  }) => {
    await loginAsAdmin(page);
    await page.goto("/databases");

    // Find a card that says "Not profiled" — no completed profile
    const cards = page.locator("h3.font-mono");
    const count = await cards.count();
    let openLink: ReturnType<typeof page.getByRole> | null = null;

    for (let i = 0; i < count; i++) {
      const h3 = cards.nth(i);
      const card = h3.locator("..").locator("..");
      if (
        await card.locator("text=Not profiled").isVisible().catch(() => false)
      ) {
        openLink = card.getByRole("link", { name: "Open" });
        break;
      }
    }

    if (!openLink) {
      test.skip(true, "No unprofiled databases found");
      return;
    }

    await openLink.click();
    await page.waitForURL(/\/databases\//);

    // Wait for the page to settle — the right sidebar should render
    await expect(page.getByText("Run profiling")).toBeVisible({ timeout: 10_000 });

    // The download button should NOT be present
    const downloadBtn = page.getByRole("button", { name: /download profile/i });
    await expect(downloadBtn).not.toBeVisible();
  });
});
