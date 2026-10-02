import { test, expect } from "@playwright/test";

const demoRuntime = { mode: "demo", backend: { status: "connected" }, providers: {} };

test("a non-English consultation shows its English translation and marks translated note fields", async ({ page }) => {
  await page.route("**/api/runtime-status*", (route) => route.fulfill({ json: demoRuntime }));
  await page.goto("/");
  await page.getByRole("button", { name: "New consultation" }).click();
  await page.getByLabel("Patient ID").fill("TELUGU-001");
  await page.getByRole("spinbutton", { name: "Age" }).fill("22");
  await page.getByLabel("Sex").selectOption("Female");
  await page.getByRole("button", { name: "Start consultation" }).click();
  await page.getByRole("button", { name: "Start demo" }).click();
  await expect(page.getByText("I've had fever for three days.")).toBeVisible({ timeout: 10000 });
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.getByText("Review before saving")).toBeVisible();

  await page.route(/\/api\/consultations\/[0-9a-f-]{36}$/, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    const id = body.id as string;
    await route.fulfill({ response, json: {
      ...body,
      transcript: [{ id: `${id}-final-0`, speaker: "UNKNOWN", text: "నిన్న రాత్రి నుంచి జ్వరం ఉంది", timestamp: "00:00:00", sequence_number: 0, language_code: "te" }],
      translation: [{ id: `${id}-en-0`, text: "I have had a fever since last night.", timestamp: "00:00:00", sequence_number: 0 }],
      record: { ...body.record, presenting_symptoms: ["fever"] },
      updates: [{ id: "u1", field_name: "presenting_symptoms", previous_value: [], new_value: ["fever"], source_segment_ids: [`${id}-en-0`], updated_at: new Date().toISOString(), update_type: "AI_EXTRACTED" }],
    } });
  });
  await page.goto("/history");
  await page.locator(".history-row", { hasText: "TELUGU-001" }).getByRole("link", { name: /Open consultation/ }).click();

  await expect(page.getByTestId("transcript-list")).toContainText("నిన్న రాత్రి నుంచి జ్వరం ఉంది");
  await page.getByRole("button", { name: "English" }).click();
  await expect(page.getByTestId("translation-list")).toContainText("I have had a fever since last night.");
  await expect(page.getByText("English translation made from the audio")).toBeVisible();
  await expect(page.getByTestId("record-presenting_symptoms")).toContainText("Translated");
  await page.getByRole("button", { name: "Original" }).click();
  await expect(page.getByTestId("transcript-list")).toBeVisible();
});
