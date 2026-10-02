import { test, expect } from "@playwright/test";

test.use({ launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] } });

const localRuntime = {
  mode: "local",
  backend: { status: "connected" },
  providers: {
    speech_to_text: { status: "ready", engine: "faster-whisper", model: "small" },
    ollama: { status: "ready" },
    silero_vad: { status: "ready" },
    faster_whisper: { status: "ready" },
    whisperx: { status: "disabled" },
    pyannote: { status: "disabled" },
  },
};

test("local microphone streams browser audio and waits for finalization before review", async ({ page }) => {
  let audioFrameCount = 0;
  let websocketConnectionCount = 0;
  let initialAudioMetadata: Record<string, unknown> | null = null;
  let receivedStop = false;
  await page.context().grantPermissions(["microphone"]);
  await page.addInitScript(() => {
    const browserWindow = window as Window & { microphoneRequestCount?: number };
    const getUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    browserWindow.microphoneRequestCount = 0;
    navigator.mediaDevices.getUserMedia = (constraints) => {
      browserWindow.microphoneRequestCount = (browserWindow.microphoneRequestCount ?? 0) + 1;
      return getUserMedia(constraints);
    };
  });
  await page.route("**/api/runtime-status*", (route) => route.fulfill({ json: localRuntime }));
  await page.routeWebSocket("**/api/consultations/*/audio", (socket) => {
    websocketConnectionCount += 1;
    socket.onMessage((message) => {
      if (typeof message === "string") {
        const parsed = JSON.parse(message) as Record<string, unknown>;
        if (!initialAudioMetadata) {
          initialAudioMetadata = parsed;
          socket.send(JSON.stringify({ type: "ready" }));
        }
        if (parsed.type === "stop") {
          receivedStop = true;
          setTimeout(() => socket.send(JSON.stringify({ type: "stopped" })), 2_500);
        }
      } else {
        audioFrameCount += 1;
      }
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "New consultation" }).click();
  await page.getByLabel("Patient ID").fill("LOCAL-MIC-BROWSER-001");
  await page.getByRole("spinbutton", { name: "Age" }).fill("42");
  await page.getByLabel("Sex").selectOption("Female");
  await page.getByLabel("Conversation language").selectOption("te");
  await page.getByRole("button", { name: "Start consultation" }).click();
  await expect(page.getByTestId("consultation-masthead")).toBeVisible();
  await expect(page.getByRole("button", { name: "Start local AI" })).toBeVisible();
  await expect(page.getByText("Live transcript")).toBeVisible();
  await expect(page.getByText("Structured clinical record")).toBeVisible();
  await page.getByRole("button", { name: "Start local AI" }).click();
  await expect.poll(() => initialAudioMetadata?.language).toBe("te");
  await expect.poll(() => page.evaluate(() => (window as Window & { microphoneRequestCount?: number }).microphoneRequestCount)).toBe(1);
  await expect.poll(() => audioFrameCount, { timeout: 5_000 }).toBeGreaterThan(0);

  const framesBeforePause = audioFrameCount;
  await page.getByRole("button", { name: "Pause" }).click();
  await page.getByRole("button", { name: "Resume" }).click();
  await expect.poll(() => page.evaluate(() => (window as Window & { microphoneRequestCount?: number }).microphoneRequestCount)).toBe(1);
  await expect.poll(() => websocketConnectionCount, { timeout: 2_000 }).toBe(1);
  await expect.poll(() => audioFrameCount, { timeout: 5_000 }).toBeGreaterThan(framesBeforePause);

  await page.getByRole("button", { name: "Stop" }).click();
  await expect.poll(() => receivedStop).toBe(true);
  await expect(page.getByText("Review before saving")).not.toBeVisible({ timeout: 500 });
  await expect(page.getByText("Review before saving")).toBeVisible({ timeout: 6_000 });
});
