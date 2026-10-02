import { expect, test } from "@playwright/test";

test("editorial shell presents a local-first rail without workspace decoration", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByTestId("editorial-sidebar")).toBeVisible();
  await expect(page.getByText("Local-first")).toBeVisible();
  await expect(page.locator(".workspace [data-testid='botanical-scene']")).toHaveCount(0);
});

test("landing opens a labelled patient intake card beside the botanical scene", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByTestId("botanical-scene")).toBeVisible();
  await page.getByRole("button", { name: "New consultation" }).click();
  await expect(page.getByLabel("Patient ID")).toBeVisible();
  await expect(page.getByLabel("Conversation language")).toBeVisible();
});

test("editorial intake and local controls remain usable at narrow width", async ({ page }) => {
  await page.route("**/api/runtime-status*", (route) => route.fulfill({ json: {
    mode: "local", backend: { status: "connected" }, providers: {
      ollama: { status: "ready" }, silero_vad: { status: "ready" }, faster_whisper: { status: "ready" },
    },
  } }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "New consultation" })).toBeVisible();
  await page.getByRole("button", { name: "New consultation" }).click();
  await expect(page.getByLabel("Patient ID")).toBeVisible();
  await page.getByLabel("Patient ID").fill("PT-390");
  const age = page.getByLabel("Age", { exact: true });
  const sex = page.getByLabel("Sex", { exact: true });
  await age.fill("42");
  const ageBox = await age.boundingBox();
  const sexBox = await sex.boundingBox();
  expect(ageBox).not.toBeNull();
  expect(sexBox).not.toBeNull();
  expect(ageBox!.x + ageBox!.width).toBeLessThanOrEqual(390);
  expect(sexBox!.x + sexBox!.width).toBeLessThanOrEqual(390);
  expect(ageBox!.y + ageBox!.height).toBeLessThanOrEqual(sexBox!.y);
  await page.getByRole("button", { name: "Start consultation" }).click();
  await expect(page.getByTestId("consultation-masthead")).toBeVisible();
  const localControl = page.getByRole("button", { name: "Start local AI" });
  await expect(localControl).toBeVisible();
  const controlBox = await localControl.boundingBox();
  expect(controlBox).not.toBeNull();
  expect(controlBox!.x + controlBox!.width).toBeLessThanOrEqual(390);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await expect(page.locator(".workspace [data-testid='botanical-scene']")).toHaveCount(0);
});

test("editorial workspace stacks clinical panels at tablet width", async ({ page }) => {
  await page.route("**/api/runtime-status*", (route) => route.fulfill({ json: {
    mode: "local", backend: { status: "connected" }, providers: {
      ollama: { status: "ready" }, silero_vad: { status: "ready" }, faster_whisper: { status: "ready" },
    },
  } }));
  await page.setViewportSize({ width: 980, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "New consultation" }).click();
  await page.getByLabel("Patient ID").fill("PT-980");
  await page.getByLabel("Age", { exact: true }).fill("42");
  await page.getByRole("button", { name: "Start consultation" }).click();
  const transcript = page.locator(".transcript-panel");
  const record = page.locator(".record-panel");
  await expect(transcript).toBeVisible();
  await expect(record).toBeVisible();
  const transcriptBox = await transcript.boundingBox();
  const recordBox = await record.boundingBox();
  expect(transcriptBox).not.toBeNull();
  expect(recordBox).not.toBeNull();
  expect(transcriptBox!.y + transcriptBox!.height).toBeLessThanOrEqual(recordBox!.y);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(980);
});
