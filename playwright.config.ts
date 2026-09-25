import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  use: { baseURL: "http://127.0.0.1:3000", ...devices["Desktop Chrome"], trace: "retain-on-failure" },
  webServer: [
    { command: "../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000", cwd: "backend", url: "http://127.0.0.1:8000/health", reuseExistingServer: true },
    { command: "npm run dev -- --hostname 127.0.0.1 --port 3000", url: "http://127.0.0.1:3000", reuseExistingServer: true },
  ],
});
