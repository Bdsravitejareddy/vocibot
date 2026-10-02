import { test, expect, type Page } from "@playwright/test";

const demoRuntime = { mode: "demo", backend: { status: "connected" }, providers: {} };
const apiUrl = "http://127.0.0.1:8001";

async function startConsultation(page: Page, patientId: string) {
  await page.goto("/");
  await page.getByRole("button", { name: "New consultation" }).click();
  await page.getByLabel("Patient ID").fill(patientId);
  await page.getByRole("spinbutton", { name: "Age" }).fill("30");
  await page.getByLabel("Sex").selectOption("Female");
  await page.getByRole("button", { name: "Start consultation" }).click();
  await expect(page.getByTestId("consultation-masthead")).toBeVisible();
}

async function stored(page: Page, patientId: string) {
  const consultations = await (await page.request.get(`${apiUrl}/api/consultations`)).json() as Array<{ patient: { patient_identifier: string } }>;
  return consultations.filter((item) => item.patient.patient_identifier === patientId).length;
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/runtime-status*", (route) => route.fulfill({ json: demoRuntime }));
});

test("a test run can be discarded mid-recording and leaves nothing behind", async ({ page }) => {
  await startConsultation(page, "DISCARD-LIVE-001");
  await page.getByRole("button", { name: "Start demo" }).click();
  await expect(page.getByText("I've had fever for three days.")).toBeVisible({ timeout: 10000 });

  await page.getByRole("button", { name: "Discard" }).click();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByTestId("consultation-masthead")).toBeVisible();
  expect(await stored(page, "DISCARD-LIVE-001")).toBe(1);

  await page.getByRole("button", { name: "Discard" }).click();
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("button", { name: "New consultation" })).toBeVisible();
  expect(await stored(page, "DISCARD-LIVE-001")).toBe(0);
});

test("saved consultations can be discarded from history and from their detail page", async ({ page }) => {
  for (const patientId of ["DISCARD-ROW-001", "DISCARD-DETAIL-001"]) {
    await startConsultation(page, patientId);
    await page.getByRole("button", { name: "Start demo" }).click();
    await expect(page.getByText("I've had fever for three days.")).toBeVisible({ timeout: 10000 });
    await page.getByRole("button", { name: "Stop" }).click();
    await expect(page.getByText("Review before saving")).toBeVisible();
  }

  await page.goto("/history");
  const row = page.locator(".history-row", { hasText: "DISCARD-ROW-001" });
  await row.getByRole("button", { name: "Discard" }).click();
  await row.getByRole("button", { name: "Confirm" }).click();
  await expect(row).toHaveCount(0);
  expect(await stored(page, "DISCARD-ROW-001")).toBe(0);

  await page.locator(".history-row", { hasText: "DISCARD-DETAIL-001" }).getByRole("link", { name: /Open consultation/ }).click();
  await expect(page.getByText("I've had fever for three days.")).toBeVisible();
  await page.getByRole("button", { name: "Discard" }).click();
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page).toHaveURL(/\/history$/);
  await expect(page.locator(".history-row", { hasText: "DISCARD-DETAIL-001" })).toHaveCount(0);
  expect(await stored(page, "DISCARD-DETAIL-001")).toBe(0);
});
