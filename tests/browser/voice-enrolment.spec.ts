import { test, expect } from "@playwright/test";

test("doctor voice: enrolled voices are listed and removable; saving needs a name and five sentences", async ({ page }) => {
  let profiles = [{ id: "v1", name: "Dr Ravi", samples: 8, created_at: "2026-10-03T10:00:00Z", threshold: 0.5 }];
  await page.route("**/api/voice-profiles", (route) => route.fulfill({ json: { available: true, profiles } }));
  await page.route("**/api/voice-profiles/v1", (route) => { profiles = []; return route.fulfill({ status: 204, body: "" }); });
  await page.goto("/settings");
  const section = page.getByTestId("voice-enrolment");
  await expect(section).toContainText("Dr Ravi");
  await expect(section).toContainText("8 sentences");
  await section.getByRole("button", { name: "Remove Dr Ravi's voice" }).click();
  await expect(section).toContainText("Dr Ravi's voice was removed.");
  await section.getByRole("button", { name: "Record the doctor's voice" }).click();
  await expect(section.getByRole("button", { name: /Record sentence \d/ })).toHaveCount(8);
  await expect(section).toContainText("జ్వరం ఎన్ని రోజుల నుంచి ఉంది?");
  await expect(section.getByRole("button", { name: /Save voice \(0\/8 recorded\)/ })).toBeDisabled();
});

test("doctor voice: without the voice model the section says so", async ({ page }) => {
  await page.route("**/api/voice-profiles", (route) => route.fulfill({ json: { available: false, profiles: [] } }));
  await page.goto("/settings");
  await expect(page.getByTestId("voice-enrolment")).toContainText("voice model is not installed");
  await expect(page.getByRole("button", { name: "Record the doctor's voice" })).toHaveCount(0);
});
