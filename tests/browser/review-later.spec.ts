import { test, expect } from "@playwright/test";

const demoRuntime = { mode: "demo", backend: { status: "connected" }, providers: {} };

test("Review later keeps the edited draft unapproved and returns to the start", async ({ page }) => {
  await page.route("**/api/runtime-status*", (route) => route.fulfill({ json: demoRuntime }));
  await page.goto("/");
  await page.getByRole("button", { name: "New consultation" }).click();
  await page.getByLabel("Patient ID").fill("LATER-001");
  await page.getByRole("spinbutton", { name: "Age" }).fill("40");
  await page.getByLabel("Sex").selectOption("Female");
  await page.getByRole("button", { name: "Start consultation" }).click();
  await page.getByRole("button", { name: "Start demo" }).click();
  await expect(page.getByText("I've had fever for three days.")).toBeVisible({ timeout: 10000 });
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.getByText("Review before saving")).toBeVisible();

  await page.getByTestId("record-follow_up").locator("input, textarea").fill("Review in one week");
  await page.getByRole("button", { name: "Review later" }).click();

  await expect(page.getByRole("button", { name: "New consultation" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Note saved for later review\. 1 note waiting for review/ })).toBeVisible();
  await page.getByRole("link", { name: /waiting for review/ }).click();
  const row = page.locator(".history-row", { hasText: "LATER-001" });
  await expect(row).toContainText("Needs review");
  await row.getByRole("link", { name: /Open consultation/ }).click();
  await expect(page.getByTestId("record-follow_up").locator("input, textarea")).toHaveValue("Review in one week");
  await expect(page.getByRole("button", { name: "Approve & Save" })).toBeVisible();
});
