import { expect, type Page } from "@playwright/test";

export const USERS = {
  owner1: "owner1@routesync.test",
  dispatcher1: "dispatcher1@routesync.test",
  owner2: "owner2@routesync.test",
} as const;

export function seedPassword(): string {
  const password = process.env.SEED_USER_PASSWORD;
  if (!password) throw new Error("SEED_USER_PASSWORD missing: run scripts/seed_dev.py first");
  return password;
}

export async function signIn(page: Page, email: string, password = seedPassword()) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

export async function signInAndWait(page: Page, email: string) {
  await signIn(page, email);
  await expect(page).toHaveURL(/\/dashboard/);
}
