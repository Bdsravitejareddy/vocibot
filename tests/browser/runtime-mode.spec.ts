import { test, expect } from "@playwright/test";

const demoRuntime = { mode: "demo", backend: { status: "connected" }, providers: {} };
const localRuntime = { mode: "local", backend: { status: "connected" }, providers: {
  ollama: { status: "ready" }, silero_vad: { status: "ready" }, faster_whisper: { status: "ready" },
  whisperx: { status: "disabled" }, pyannote: { status: "disabled" },
} };

test("demo runtime renders demo labels and no local microphone workflow", async ({ page }) => {
  await page.route("**/api/runtime-status", (route) => route.fulfill({ json: demoRuntime }));
  await page.goto("/");
  await expect(page.getByText("Demo mode", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "New consultation" }).click();
  await expect(page.getByText("Deterministic scripted provider")).toBeVisible();
  await expect(page.getByText("Demo mode is ready")).not.toBeVisible();
});

test("local runtime renders local status and local microphone action", async ({ page }) => {
  await page.route("**/api/runtime-status", (route) => route.fulfill({ json: localRuntime }));
  await page.goto("/");
  await expect(page.getByText("Local AI", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "New consultation" }).click();
  await expect(page.getByText("Local microphone pipeline")).toBeVisible();
  await expect(page.locator("span", { hasText: "Ollama Ready" }).locator("b")).toHaveText("Ready");
  await expect(page.getByText("Demo mode is ready")).not.toBeVisible();
});
