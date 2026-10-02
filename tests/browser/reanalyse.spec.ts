import { test, expect } from "@playwright/test";

const demoRuntime = { mode: "demo", backend: { status: "connected" }, providers: {} };

test("a saved consultation shows its session ID, can be re-analysed and approved from history", async ({ page }) => {
  await page.route("**/api/runtime-status*", (route) => route.fulfill({ json: demoRuntime }));
  await page.goto("/");
  await page.getByRole("button", { name: "New consultation" }).click();
  await page.getByLabel("Patient ID").fill("REANALYSE-BROWSER-001");
  await page.getByRole("spinbutton", { name: "Age" }).fill("30");
  await page.getByLabel("Sex").selectOption("Female");
  await page.getByRole("button", { name: "Start consultation" }).click();
  const liveCode = await page.getByTestId("session-code").textContent();
  expect(liveCode).toMatch(/^Session VB-\d{8}-[0-9A-Z]{6}$/);
  await page.getByRole("button", { name: "Start demo" }).click();
  await expect(page.getByText("I've had fever for three days.")).toBeVisible({ timeout: 10000 });
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.getByText("Review before saving")).toBeVisible();

  await page.goto("/history");
  const row = page.locator(".history-row", { hasText: "REANALYSE-BROWSER-001" });
  await expect(row).toContainText(liveCode!.replace("Session ", ""));
  await row.getByRole("link", { name: /Open consultation/ }).click();
  await expect(page.getByTestId("session-code")).toHaveText(liveCode!);
  await expect(page.getByTestId("recordings")).toContainText("No audio was stored");
  await expect(page.getByRole("button", { name: "Re-transcribe" })).toHaveCount(0);

  await page.getByRole("button", { name: "Re-analyse note" }).click();
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("button", { name: "Re-analyse note" })).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId("record-chief_complaint").locator("input")).toHaveValue(/fever/i);

  await page.getByTestId("record-chief_complaint").locator("input").fill("Fever — reviewed from history");
  await page.getByRole("button", { name: "Approve & Save" }).click();
  await expect(page.getByText("Approved record")).toBeVisible();
  await expect(page.locator('input[value="Fever — reviewed from history"]')).toBeVisible();
});
