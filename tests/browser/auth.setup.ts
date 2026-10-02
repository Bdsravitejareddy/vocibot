import { test as setup, expect } from "@playwright/test";
import { ADMIN, API_URL, STORAGE_STATE } from "./fixtures";

setup("create the administrator and sign in", async ({ request }) => {
  const setupResponse = await request.post(`${API_URL}/api/auth/setup`, { data: ADMIN });
  expect([200, 409]).toContain(setupResponse.status());
  const login = await request.post(`${API_URL}/api/auth/login`, { data: { username: ADMIN.username, password: ADMIN.password } });
  expect(login.ok()).toBeTruthy();
  await request.storageState({ path: STORAGE_STATE });
});
