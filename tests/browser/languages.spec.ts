import { test, expect } from "@playwright/test";

const demoRuntime = { mode: "demo", backend: { status: "connected" }, providers: {} };

test("only the languages enabled in Settings are offered and used for auto-detect", async ({ page }) => {
  await page.route("**/api/runtime-status*", (route) => route.fulfill({ json: demoRuntime }));
  await page.goto("/settings");
  await expect(page.getByTestId("enabled-languages")).toContainText("Telugu");
  for (const name of ["Marathi", "Gujarati"]) await page.getByLabel(name, { exact: true }).uncheck();
  await page.getByLabel("Find a language").fill("kann");
  await expect(page.getByLabel("Kannada", { exact: true })).not.toBeChecked();
  await page.getByRole("button", { name: "Save languages" }).click();
  await expect(page.getByRole("status")).toContainText("Saved");
  await expect(page.getByTestId("enabled-languages")).toHaveText(/English.*Hindi.*Telugu|English.*Telugu.*Hindi/);

  await page.goto("/");
  await page.getByRole("button", { name: "New consultation" }).click();
  const menu = page.getByLabel("Conversation language");
  await expect(menu.locator("option")).toHaveText([/Auto-detect \(English, (Telugu, Hindi|Hindi, Telugu)\)/, /English/, /Telugu|Hindi/, /Telugu|Hindi/]);

  // Restore the defaults for other tests.
  await page.request.put("http://127.0.0.1:8001/api/settings/languages", { data: { enabled: ["en", "te", "hi", "mr", "gu"] } });
});
