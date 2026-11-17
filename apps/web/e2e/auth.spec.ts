import { expect, test } from "@playwright/test";

import { signIn, signInAndWait, USERS } from "./helpers";

test("signed-out visitor is redirected from the dashboard to sign-in", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
});

test("every dashboard address is protected", async ({ page }) => {
  for (const path of ["/dashboard/journeys", "/dashboard/services", "/dashboard/buses"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/login$/);
  }
});

test("wrong password shows an error and stays on sign-in", async ({ page }) => {
  await signIn(page, USERS.owner1, "definitely-not-the-password");
  await expect(page.getByRole("alert").filter({ hasText: "Sign-in failed" })).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
});

test("the password can be shown and hidden", async ({ page }) => {
  await page.goto("/login");
  const password = page.getByLabel("Password", { exact: true });
  await expect(password).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Show password" }).click();
  await expect(password).toHaveAttribute("type", "text");
  await page.getByRole("button", { name: "Hide password" }).click();
  await expect(password).toHaveAttribute("type", "password");
});

test("owner signs in, sees own operator, and signs out", async ({ page }) => {
  await signInAndWait(page, USERS.owner1);
  const profile = page.getByTestId("operator-profile");
  await expect(profile).toContainText("Shivneri Travels");
  await expect(profile).toContainText("owner");

  const localStorageKeys = await page.evaluate(() => Object.keys(window.localStorage));
  expect(localStorageKeys.filter((key) => key.includes("auth-token"))).toEqual([]);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
});

test("a second operator sees only its own operator", async ({ page }) => {
  await signInAndWait(page, USERS.owner2);
  const profile = page.getByTestId("operator-profile");
  await expect(profile).toContainText("Deccan Express");
  await expect(profile).not.toContainText("Shivneri");
});

test("a dispatcher signs in with the dispatcher role", async ({ page }) => {
  await signInAndWait(page, USERS.dispatcher1);
  await expect(page.getByTestId("operator-profile")).toContainText("dispatcher");
});
