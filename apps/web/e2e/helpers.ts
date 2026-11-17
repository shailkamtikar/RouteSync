import { expect, type Locator, type Page } from "@playwright/test";

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
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

export async function signInAndWait(page: Page, email: string) {
  await signIn(page, email);
  await expect(page).toHaveURL(/\/dashboard/);
}

/** The sidebar navigation. */
export const nav = (page: Page) => page.getByRole("navigation", { name: "Main" });

/** The open dialog (the native element is only exposed while it is open). */
export const dialog = (page: Page) => page.getByRole("dialog");

/** Chooses a place in a search-as-you-type picker. */
export async function pickPlace(scope: Page | Locator, label: string, query: string, pick = query) {
  const box = scope.getByRole("combobox", { name: label, exact: true });
  await box.click();
  await box.fill(query);
  await scope.getByRole("option", { name: new RegExp(`^${pick}`) }).first().click();
}

/** A stop in the monitor's list of stops. */
export function stopItem(page: Page, name: string): Locator {
  return page
    .getByRole("list", { name: "Stop events" })
    .getByRole("listitem")
    .filter({ has: page.locator("strong", { hasText: new RegExp(`^${name}$`) }) });
}

/** A local date-time string far in the future, different on every call, for datetime-local inputs. */
let counter = 0;
export function futureLocal(hour = 22): string {
  counter += 1;
  const day = new Date(Date.now() + (500 + (Date.now() % 900) + counter * 3) * 86_400_000);
  return `${day.toISOString().slice(0, 10)}T${String(hour).padStart(2, "0")}:00`;
}

/** Removes a service by its cities if an earlier run left it behind. */
export async function removeServiceIfPresent(page: Page, origin: string, destination: string) {
  await page.goto("/dashboard/services");
  await expect(page.getByRole("heading", { name: "Services" })).toBeVisible();
  await expect(page.getByTestId("service-card").first()).toBeVisible({ timeout: 20_000 }).catch(() => {});
  const card = page.getByTestId("service-card").filter({ hasText: origin }).filter({ hasText: destination });
  if ((await card.count()) > 0) {
    await card.getByRole("button", { name: new RegExp(`^Remove ${origin} to ${destination}`) }).click();
    await dialog(page).getByRole("button", { name: "Remove service" }).click();
    await expect(card).toHaveCount(0);
  }
}
