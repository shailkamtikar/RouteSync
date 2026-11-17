import { expect, test } from "@playwright/test";

import { dialog, nav, signInAndWait, USERS } from "./helpers";

// These read the operator's seeded network (scripts/seed_network.py) and change nothing.
test("the overview summarises the operation and links into the work", async ({ page }) => {
  await signInAndWait(page, USERS.owner1);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Good (morning|afternoon|evening), Shivneri Travels/);

  const glance = page.getByRole("region", { name: "Today at a glance" });
  await expect(glance).toContainText("On the road");
  await expect(glance).toContainText("Boarding now");
  await expect(glance).toContainText("Departing in 24 h");
  await expect(glance).toContainText("Need your action");
  await expect(glance).toContainText("Passengers today");

  await expect(page.getByRole("region", { name: "Network map" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Live now" })).toBeVisible();
  const departures = page.getByRole("region", { name: "Next departures" });
  await expect(departures.getByRole("listitem").first()).toBeVisible();

  // A departure opens its journey.
  await departures.getByRole("listitem").first().getByRole("link").click();
  await expect(page).toHaveURL(/\/dashboard\/journeys\/[0-9a-f-]+$/);
});

test("a live journey on the overview opens its monitor, and the map shows the buses", async ({ page }) => {
  await signInAndWait(page, USERS.owner1);
  const live = page.getByRole("region", { name: "Live now" });
  const link = live.getByRole("link", { name: /Monitor/ }).first();
  await expect(link).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("region", { name: "Network map" })).toContainText(/buses reporting|No bus/);
  await link.click();
  await expect(page).toHaveURL(/\/monitor$/);
  await expect(page.getByTestId("next-stop-card")).toBeVisible();
});

test("New journey on the overview opens the journey form", async ({ page }) => {
  await signInAndWait(page, USERS.owner1);
  await page.getByRole("link", { name: "New journey" }).click();
  await expect(page).toHaveURL(/\/dashboard\/journeys/);
  await expect(dialog(page).getByRole("form", { name: "New journey" })).toBeVisible();
  await dialog(page).getByRole("button", { name: "Cancel" }).click();
  await expect(nav(page).getByRole("link", { name: "Journeys" })).toHaveAttribute("aria-current", "page");
});
