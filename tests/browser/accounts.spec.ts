import { test, expect, type Page } from "@playwright/test";
import { ADMIN } from "./fixtures";

const demoRuntime = { mode: "demo", backend: { status: "connected" }, providers: {} };

async function signIn(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test.describe("accounts", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("signed-out visitors are sent to sign-in and wrong passwords are refused", async ({ page }) => {
    await page.goto("/history");
    await expect(page).toHaveURL(/\/login\?next=%2Fhistory/);
    await page.getByLabel("Username").fill(ADMIN.username);
    await page.getByLabel("Password").fill("not-the-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.locator(".form-error")).toHaveText("Incorrect username or password.");
    await page.getByLabel("Password").fill(ADMIN.password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/history$/);
    await expect(page.getByTestId("account-card")).toContainText("Clinic Admin");
  });

  test("an administrator adds a doctor who must set a password and sees only their own records", async ({ browser }) => {
    const adminContext = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    const admin = await adminContext.newPage();
    await admin.route("**/api/runtime-status*", (route) => route.fulfill({ json: demoRuntime }));
    await signIn(admin, ADMIN.username, ADMIN.password);
    await expect(admin.getByTestId("account-card")).toBeVisible();

    // The administrator records a consultation of their own.
    await admin.goto("/");
    await admin.getByRole("button", { name: "New consultation" }).click();
    await admin.getByLabel("Patient ID").fill("ADMIN-PRIVATE-001");
    await admin.getByRole("spinbutton", { name: "Age" }).fill("50");
    await admin.getByLabel("Sex").selectOption("Male");
    await admin.getByRole("button", { name: "Start consultation" }).click();
    await expect(admin.getByTestId("consultation-masthead")).toBeVisible();

    await admin.goto("/admin");
    await admin.getByLabel("Full name").fill("Dr Priya Rao");
    await admin.getByLabel("Username").fill("dr.rao");
    const temporary = await admin.getByLabel("Temporary password").inputValue();
    await admin.getByRole("button", { name: "Create account" }).click();
    await expect(admin.getByRole("status")).toContainText(`temporary password: ${temporary}`);
    await expect(admin.getByTestId("user-dr.rao")).toContainText("Temporary password");

    const doctorContext = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    const doctor = await doctorContext.newPage();
    await signIn(doctor, "dr.rao", temporary);
    await expect(doctor).toHaveURL(/\/account\?required=1/);
    await expect(doctor.getByText("Choose your own password to continue.")).toBeVisible();
    await doctor.getByLabel("Temporary password").fill(temporary);
    await doctor.getByLabel("New password (at least 10 characters)").fill("raos-own-password");
    await doctor.getByLabel("Confirm new password").fill("raos-own-password");
    await doctor.getByRole("button", { name: "Change password" }).click();
    await expect(doctor).toHaveURL(/\/login/);

    await signIn(doctor, "dr.rao", "raos-own-password");
    await doctor.goto("/history");
    await expect(doctor.getByText("No consultations saved yet")).toBeVisible();
    await expect(doctor.getByText("ADMIN-PRIVATE-001")).toHaveCount(0);
    await expect(doctor.getByRole("link", { name: /Users & security/ })).toHaveCount(0);
    await doctor.goto("/admin");
    await expect(doctor.getByText("Administrator access is required.")).toBeVisible();

    // Deactivation signs the doctor out everywhere.
    await admin.goto("/admin");
    await admin.getByTestId("user-dr.rao").getByRole("button", { name: "Deactivate" }).click();
    await expect(admin.getByRole("status")).toContainText("deactivated");
    await doctor.goto("/history");
    await expect(doctor).toHaveURL(/\/login/);

    await adminContext.close();
    await doctorContext.close();
  });
});
