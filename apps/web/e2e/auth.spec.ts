import { expect, test } from "@playwright/test";

import { signIn, signInAndWait, USERS } from "./helpers";

test("signed-out visitor is redirected from the dashboard to sign-in", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
});

test("wrong password shows an error and stays on sign-in", async ({ page }) => {
  await signIn(page, USERS.owner1, "definitely-not-the-password");
  await expect(page.getByText("Sign-in failed")).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
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
