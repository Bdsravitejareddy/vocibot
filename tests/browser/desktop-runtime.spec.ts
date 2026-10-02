import { test, expect } from "@playwright/test";

test("desktop renderer exposes local language setup and local-only readiness", async ({ page }) => {
  const observedOrigins = new Set<string>();
  page.on("request", (request) => observedOrigins.add(new URL(request.url()).origin));
  await page.route("**/api/runtime-status*", (route) => route.fulfill({ json: {
    mode: "local",
    backend: { status: "connected" },
    providers: {
      ollama: { status: "ready" },
      speech_to_text: { status: "ready", engine: "whisper", model: "small" },
      silero_vad: { status: "ready" },
      whisperx: { status: "disabled" },
      pyannote: { status: "disabled" },
    },
  } }));
  await page.goto("/");
  await page.getByRole("button", { name: "New consultation" }).click();
  const language = page.getByLabel("Conversation language");
  // Default enabled languages; auto-detect only chooses among them.
  await expect(language.locator("option")).toHaveText(["Auto-detect (English, Hindi, Telugu, Marathi, Gujarati)", "English (incl. Indian English)", "Hindi", "Telugu", "Marathi", "Gujarati"]);
  await expect(page.getByText("Local microphone pipeline")).toBeVisible();
  expect([...observedOrigins].every((origin) => origin.includes("127.0.0.1") || origin.includes("localhost"))).toBe(true);
});
