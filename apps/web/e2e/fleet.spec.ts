import { expect, test } from "@playwright/test";

import { dialog, nav, pickPlace, removeServiceIfPresent, signInAndWait, USERS } from "./helpers";

const suffix = Date.now().toString().slice(-6);

test("operator manages a bus: add, duplicate rejected, edit, remove", async ({ page }) => {
  const registration = `E2E ${suffix}`;
  await signInAndWait(page, USERS.owner2);
  await nav(page).getByRole("link", { name: "Buses" }).click();
  await expect(page.getByRole("heading", { name: "Buses" })).toBeVisible();

  await page.getByRole("button", { name: "Add bus" }).click();
  const add = dialog(page);
  await add.getByLabel("Registration").fill(registration);
  await add.getByLabel("Seats").fill("36");
  await add.getByRole("button", { name: "Add bus" }).click();
  const card = page.getByTestId("bus-card").filter({ hasText: registration });
  await expect(card).toContainText("36 seats");
  await expect(card).toContainText("Available");

  // The same registration cannot be added twice.
  await page.getByRole("button", { name: "Add bus" }).click();
  await dialog(page).getByLabel("Registration").fill(registration);
  await dialog(page).getByRole("button", { name: "Add bus" }).click();
  await expect(dialog(page).getByRole("alert")).toContainText("already exists");
  await dialog(page).getByRole("button", { name: "Cancel" }).click();

  await card.getByRole("button", { name: `Edit ${registration}` }).click();
  await dialog(page).getByLabel("Seats").fill("44");
  await dialog(page).getByRole("button", { name: "Save changes" }).click();
  await expect(card).toContainText("44 seats");

  // Search narrows the fleet.
  await page.getByLabel("Search buses").fill(registration);
  await expect(page.getByTestId("bus-card")).toHaveCount(1);
  await page.getByLabel("Search buses").fill("");

  await card.getByRole("button", { name: `Remove ${registration}` }).click();
  await dialog(page).getByRole("button", { name: "Remove bus" }).click();
  await expect(card).toHaveCount(0);
});

test("operator adds and removes a service; another operator cannot see it", async ({ page, browser }) => {
  test.setTimeout(240_000);
  await signInAndWait(page, USERS.owner2);
  await removeServiceIfPresent(page, "Dhule", "Nandurbar");

  await page.getByRole("button", { name: "New service" }).click();
  const create = dialog(page);
  await expect(create.getByRole("button", { name: "Create service" })).toBeDisabled();
  await pickPlace(create, "Origin", "Dhul", "Dhule");
  await pickPlace(create, "Destination", "Nandur", "Nandurbar");
  await expect(create).toContainText("No ready-made corridor");
  await create.getByRole("button", { name: "Create service" }).click();

  await expect(page).toHaveURL(/\/dashboard\/services\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { name: /Dhule.*Nandurbar/ })).toBeVisible();
  await expect(page.getByText("No route options yet")).toBeVisible();

  // The same pair cannot be created twice.
  await nav(page).getByRole("link", { name: "Services" }).click();
  await page.getByRole("button", { name: "New service" }).click();
  await pickPlace(dialog(page), "Origin", "Dhul", "Dhule");
  await pickPlace(dialog(page), "Destination", "Nandur", "Nandurbar");
  await expect(dialog(page)).toContainText("You already run Dhule");
  await expect(dialog(page).getByRole("button", { name: "Create service" })).toBeDisabled();
  await dialog(page).getByRole("button", { name: "Cancel" }).click();

  // Another operator does not see it.
  const otherContext = await browser.newContext();
  const other = await otherContext.newPage();
  await signInAndWait(other, USERS.owner1);
  await other.goto("/dashboard/services");
  await expect(other.getByTestId("service-card").first()).toBeVisible({ timeout: 20_000 });
  await expect(other.getByTestId("service-card").filter({ hasText: "Nandurbar" })).toHaveCount(0);
  await otherContext.close();

  await removeServiceIfPresent(page, "Dhule", "Nandurbar");
});

test("the place picker works with the keyboard and explains an empty search", async ({ page }) => {
  await signInAndWait(page, USERS.owner2);
  await page.goto("/dashboard/services");
  await page.getByRole("button", { name: "New service" }).click();
  const box = dialog(page).getByRole("combobox", { name: "Origin", exact: true });
  await box.click();
  await box.fill("kolh");
  await expect(dialog(page).getByRole("option", { name: /^Kolhapur/ })).toBeVisible();
  await box.press("ArrowDown");
  await box.press("ArrowUp");
  await box.press("Enter");
  await expect(box).toHaveValue("Kolhapur");

  // Old names find the current place, and nonsense is explained.
  await box.fill("aurangabad");
  await expect(dialog(page).getByRole("option", { name: /Chhatrapati Sambhajinagar/ })).toBeVisible();
  await box.fill("zzzzqq");
  await expect(dialog(page)).toContainText("No Maharashtra place matches");
  await page.keyboard.press("Escape");
});
