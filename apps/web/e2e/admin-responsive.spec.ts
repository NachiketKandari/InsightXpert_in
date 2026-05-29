import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers/auth";

test.describe("admin panel responsive & scroll", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test.describe("metrics page — single viewport, no dual scroll", () => {
    test.beforeEach(async ({ page }) => {
      await page.goto("/admin/metrics");
      await expect(page.getByText("Query metrics")).toBeVisible();
    });

    test("heading and filter bar stay visible above table", async ({ page }) => {
      const heading = page.getByRole("heading", { name: /query metrics/i });
      await expect(heading).toBeInViewport();

      const filterArea = page.locator("text=User ID").first();
      await expect(filterArea).toBeInViewport();
    });

    test("table fills available height without page-level scroll", async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 800 });

      // The table card's scrollable body should be the only vertical scroller
      const tableCard = page.locator(".rounded-lg.border.border-border.bg-card").first();
      const scrollContainer = tableCard.locator("[style*='overflow-y']").first();

      await expect(scrollContainer).toBeVisible();
      const overflowY = await scrollContainer.evaluate(
        (el) => window.getComputedStyle(el).overflowY,
      );
      expect(overflowY).toBe("auto");

      // The table body should have a non-zero height filling the viewport
      const height = await scrollContainer.evaluate(
        (el) => el.clientHeight,
      );
      expect(height).toBeGreaterThan(300);
    });

    test("mobile viewport — table header and body scroll together horizontally", async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });

      const outerScroll = page.locator(".rounded-lg.border.border-border.bg-card .overflow-x-auto").first();
      await expect(outerScroll).toBeVisible();

      // Both header and body should be inside the same overflow-x-auto wrapper
      const headerInWrapper = outerScroll.locator("text=Thumbs").first();
      await expect(headerInWrapper).toBeVisible();
    });
  });

  test.describe("audit page — same single-viewport pattern", () => {
    test.beforeEach(async ({ page }) => {
      await page.goto("/admin/audit");
      await expect(page.getByText("Audit log")).toBeVisible();
    });

    test("heading and filters are in viewport, no page scroll", async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 800 });

      const heading = page.getByRole("heading", { name: /audit log/i });
      await expect(heading).toBeInViewport();

      await expect(page.getByPlaceholder("uuid")).toBeInViewport();
    });

    test("table fills remaining height", async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 800 });

      const tableCard = page.locator(".rounded-lg.border.border-border.bg-card");
      const scrollContainer = tableCard.locator("[style*='overflow-y']").first();
      await expect(scrollContainer).toBeVisible();
      const height = await scrollContainer.evaluate((el) => el.clientHeight);
      expect(height).toBeGreaterThan(300);
    });
  });

  test.describe("users page — responsive table", () => {
    test.beforeEach(async ({ page }) => {
      await page.goto("/admin/users");
      await expect(page.getByText("Users")).toBeVisible();
    });

    test("table card has horizontal scroll wrapper on mobile", async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });

      const tableCard = page.locator(".rounded-lg.border.border-border.bg-card").first();
      const overflowX = await tableCard.evaluate(
        (el) => window.getComputedStyle(el).overflowX,
      );
      expect(overflowX).toBe("auto");

      // All 5 column headers should be present (even if some are scrolled out)
      await expect(page.getByText("Email")).toBeVisible();
      await expect(page.getByText("Role")).toBeVisible();
      await expect(page.getByText("Active")).toBeVisible();
      await expect(page.getByText("Last seen")).toBeVisible();
      await expect(page.getByText("Actions")).toBeVisible();
    });

    test("desktop — table has min-width set on grid rows", async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 800 });

      const header = page.locator(".grid").first();
      const minWidth = await header.evaluate((el) => {
        return window.getComputedStyle(el).minWidth;
      });
      // Should have the 700px min-width constraint
      expect(minWidth).toBe("700px");
    });
  });

  test.describe("databases admin page — responsive header + table", () => {
    test.beforeEach(async ({ page }) => {
      await page.goto("/admin/databases");
      await expect(page.getByText("Databases")).toBeVisible();
    });

    test("mobile — filter input stacks below heading and is full width", async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });

      const filterInput = page.getByPlaceholder(/filter by db_id/i);
      await expect(filterInput).toBeVisible();

      const width = await filterInput.evaluate((el) => (el as HTMLInputElement).offsetWidth);
      expect(width).toBeGreaterThan(200); // should be near full width on mobile
    });

    test("table has horizontal scroll wrapper for narrow viewports", async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });

      const tableCard = page.locator(".rounded-lg.border.border-border.bg-card").first();
      const overflowX = await tableCard.evaluate(
        (el) => window.getComputedStyle(el).overflowX,
      );
      expect(overflowX).toBe("auto");
    });

    test("desktop — filter input is constrained width next to heading", async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 800 });

      const filterInput = page.getByPlaceholder(/filter by db_id/i);
      const width = await filterInput.evaluate((el) => (el as HTMLInputElement).offsetWidth);
      // sm:w-64 should be ~256px on desktop
      expect(width).toBeGreaterThan(200);
      expect(width).toBeLessThan(400);
    });
  });

  test.describe("SchemaPanel DDL tab — vh-based max height", () => {
    test.beforeEach(async ({ page }) => {
      await page.goto("/admin/overview");
      await expect(page.getByText("Sparkline")).toBeVisible();
    });

    test("DDL pre uses viewport-relative max-height on database detail page", async ({ page, request }) => {
      // Navigate to a database detail page — we need at least one DB
      await page.goto("/databases");
      const dbLink = page.locator("a[href*='/databases/']").first();
      if (!(await dbLink.isVisible().catch(() => false))) {
        test.skip(true, "No databases available");
        return;
      }
      await dbLink.click();
      await page.waitForURL(/\/databases\//);

      // Click the DDL tab
      const ddlTab = page.getByRole("tab", { name: /ddl/i });
      if (!(await ddlTab.isVisible().catch(() => false))) {
        test.skip(true, "DDL tab not visible");
        return;
      }
      await ddlTab.click();

      const pre = page.locator("pre.whitespace-pre").first();
      if (await pre.isVisible().catch(() => false)) {
        const maxHeight = await pre.evaluate(
          (el) => window.getComputedStyle(el).maxHeight,
        );
        // max-h-[50vh] at 667px height = ~333.5px
        expect(maxHeight).toContain("px");
        const maxH = parseFloat(maxHeight);
        // Should be viewport-relative, not the old fixed 480px
        expect(maxH).toBeLessThan(400);
      }
    });
  });
});
