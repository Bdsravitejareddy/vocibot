import { test, expect } from "@playwright/test";

test("live page reflects the backend runtime mode", async ({ page, request }) => {
  const response = await request.get("http://127.0.0.1:8001/api/runtime-status");
  expect(response.ok()).toBeTruthy();
  const runtime = await response.json() as { mode: "demo" | "local" };
  await page.goto("/");
  await expect(page.getByText(runtime.mode === "local" ? "Local AI" : "Demo mode", { exact: true }).first()).toBeVisible();
});
