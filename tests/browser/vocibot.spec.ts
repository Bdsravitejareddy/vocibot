import { test, expect } from "@playwright/test";

const demoRuntime = { mode: "demo", backend: { status: "connected" }, providers: {} };

test("demo consultation streams transcript and fills the record progressively", async ({ page }) => {
  await page.route("**/api/runtime-status*", (route) => route.fulfill({ json: demoRuntime }));
  await page.goto("/");
  await page.getByRole("button", { name: "New consultation" }).click();
  await page.getByLabel("Patient ID").fill("DEMO-BROWSER-001");
  await page.getByRole("spinbutton", { name: "Age" }).fill("42");
  await page.getByLabel("Sex").selectOption("Female");
  await page.getByRole("button", { name: "Start consultation" }).click();
  await expect(page.getByTestId("consultation-masthead")).toBeVisible();
  await expect(page.getByText("Live transcript")).toBeVisible();
  await expect(page.getByText("Structured clinical record")).toBeVisible();
  await page.getByRole("button", { name: "Start demo" }).click();
  await expect(page.getByText("I've had fever for three days.")).toBeVisible({ timeout: 10000 });
  const displayedTimes = await page.locator(".transcript-item time").evaluateAll((nodes) => nodes.map((node) => node.textContent ?? ""));
  expect(displayedTimes.length).toBeGreaterThan(0);
  for (const value of displayedTimes) expect(value).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  await expect(page.getByTestId("record-chief_complaint").locator("input")).toHaveValue(/fever/i, { timeout: 10000 });
  await expect(page.getByTestId("record-presenting_symptoms").locator("input")).toHaveValue(/dry cough/i, { timeout: 10000 });
  await page.getByRole("button", { name: "Stop" }).click();
  const durationText = await page.locator(".timer").textContent();
  const durationSeconds = durationText ? durationText.split(":").reduce((total, part) => total * 60 + Number(part), 0) : 0;
  const finalTimes = await page.locator(".transcript-item time").evaluateAll((nodes) => nodes.map((node) => (node.textContent ?? "").split(":").reduce((total, part) => total * 60 + Number(part), 0)));
  for (const timestampSeconds of finalTimes) {
    expect(timestampSeconds).toBeGreaterThanOrEqual(0);
    expect(timestampSeconds).toBeLessThanOrEqual(durationSeconds);
  }
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
