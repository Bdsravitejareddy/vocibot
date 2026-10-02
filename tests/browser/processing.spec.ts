import { test, expect } from "@playwright/test";

test.use({ launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] } });

const localRuntime = { mode: "local", backend: { status: "connected" }, providers: { speech_to_text: { status: "ready", engine: "mlx_whisper" }, ollama: { status: "ready" }, silero_vad: { status: "ready" } } };

test("after Stop the note is prepared in the background and review opens when it is ready", async ({ page }) => {
  await page.context().grantPermissions(["microphone"]);
  await page.route("**/api/runtime-status*", (route) => route.fulfill({ json: localRuntime }));
  await page.routeWebSocket("**/api/consultations/*/audio", (socket) => {
    socket.onMessage((message) => {
      if (typeof message !== "string") return;
      const parsed = JSON.parse(message) as { type?: string };
      if (parsed.type === "stop") socket.send(JSON.stringify({ type: "stopped" }));
      else socket.send(JSON.stringify({ type: "ready", live_preview: true }));
    });
  });
  let polls = 0;
  await page.route("**/api/consultations/*/stop", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, processing: { status: "queued", plan: "transcribe,note", error: null, warnings: [], jobs_ahead: 1 } } });
  });
  await page.route(/\/api\/consultations\/[0-9a-f-]{36}$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    polls += 1;
    const processing = polls < 2 ? { status: "writing_note", plan: "transcribe,note", error: null, warnings: [], jobs_ahead: null } : { status: "done", plan: "transcribe,note", error: null, warnings: [], jobs_ahead: null };
    await route.fulfill({ response, json: { ...body, processing, record: polls < 2 ? body.record : { ...body.record, chief_complaint: "dizziness and nausea" } } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "New consultation" }).click();
  await page.getByLabel("Patient ID").fill("PROCESSING-001");
  await page.getByRole("spinbutton", { name: "Age" }).fill("30");
  await page.getByLabel("Sex").selectOption("Female");
  await page.getByRole("button", { name: "Start consultation" }).click();
  await page.getByRole("button", { name: "Start local AI" }).click();
  await page.getByRole("button", { name: "Stop" }).click();

  await expect(page.getByTestId("processing-banner")).toContainText("1 consultation ahead of yours");
  await expect(page.getByText("Review before saving")).toHaveCount(0);
  await expect(page.getByTestId("record-chief_complaint").locator("input")).toBeDisabled();
  await expect(page.getByTestId("processing-banner")).toContainText("Writing the clinical note", { timeout: 5000 });
  await expect(page.getByText("Review before saving")).toBeVisible({ timeout: 8000 });
  await expect(page.getByTestId("processing-banner")).toHaveCount(0);
  await expect(page.getByTestId("record-chief_complaint").locator("input")).toHaveValue("dizziness and nausea");
});
