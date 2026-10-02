import { defineConfig, devices } from "@playwright/test";

const apiUrl = "http://127.0.0.1:8001";
const webUrl = "http://127.0.0.1:3001";
const databaseUrl = `sqlite:////tmp/vocibot-playwright-${process.pid}.sqlite`;

export default defineConfig({
  testDir: "./tests/browser",
  workers: 1,
  use: { baseURL: webUrl, ...devices["Desktop Chrome"], trace: "retain-on-failure" },
  webServer: [
    {
      command: "../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001",
      cwd: "backend",
      url: `${apiUrl}/health`,
      env: { AI_MODE: "demo", DATABASE_URL: databaseUrl },
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --hostname 127.0.0.1 --port 3001",
      url: webUrl,
      env: { NEXT_PUBLIC_API_URL: apiUrl },
      reuseExistingServer: false,
    },
  ],
});
