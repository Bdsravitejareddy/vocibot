import { test, expect } from "@playwright/test";

test("demo consultation streams transcript and fills the record progressively", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "New consultation" }).click();
  await page.getByLabel("Patient ID").fill("DEMO-BROWSER-001");
  await page.getByLabel("Age").fill("42");
  await page.getByLabel("Sex").selectOption("Female");
  await page.getByRole("button", { name: "Start consultation" }).click();
  await page.getByRole("button", { name: "Start demo" }).click();
  await expect(page.getByText("I've had fever for three days.")).toBeVisible({ timeout: 10000 });
  await expect(page.getByTestId("record-chief_complaint").locator("input")).toHaveValue("Fever", { timeout: 10000 });
  await expect(page.getByTestId("record-presenting_symptoms").locator("input")).toHaveValue(/Dry cough/, { timeout: 10000 });
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.getByText("Review before saving")).toBeVisible();
  await page.getByTestId("record-chief_complaint").locator("input").fill("Fever — doctor reviewed");
  await page.getByRole("button", { name: "Approve & Save" }).click();
  await expect(page.getByText("Approved and saved")).toBeVisible();
  await page.getByRole("link", { name: "Consultation history" }).click();
  await expect(page.getByText("DEMO-BROWSER-001")).toBeVisible();
  await page.getByRole("link", { name: /Open consultation/ }).first().click();
  await expect(page.getByText("I've had fever for three days.")).toBeVisible();
  await expect(page.locator('input[value="Fever — doctor reviewed"]')).toBeVisible();
  await expect(page.getByText(/Source:/).first()).toBeVisible();
});
