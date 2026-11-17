import { expect, test } from "@playwright/test";

import { dialog, pickPlace, removeServiceIfPresent, signInAndWait, USERS } from "./helpers";

test("a known corridor comes with route options, each with its own stops", async ({ page }) => {
  test.setTimeout(300_000);
  await signInAndWait(page, USERS.owner2);
  await removeServiceIfPresent(page, "Pune", "Shirdi");

  await page.getByRole("button", { name: "New service" }).click();
  await pickPlace(dialog(page), "Origin", "Pune");
  await pickPlace(dialog(page), "Destination", "Shirdi");
  await expect(dialog(page)).toContainText("Add 2 known route options");
  await dialog(page).getByRole("button", { name: "Create service" }).click();

  // Both roads are drawn, and the map credits OpenStreetMap.
  const options = page.getByTestId("route-option");
  await expect(options).toHaveCount(2, { timeout: 120_000 });
  await expect(options.first()).toContainText("Ready");
  await expect(options.nth(1)).toContainText("Ready");
  await expect(page.getByRole("link", { name: /OpenStreetMap contributors/ }).first()).toBeVisible();

  // The stops belong to the selected option only.
  const stops = page.getByTestId("route-stops");
  await options.filter({ hasText: "Via Narayangaon and Sangamner" }).getByRole("button").first().click();
  await expect(stops).toContainText("Sangamner");
  await expect(stops).not.toContainText("Shirur");
  await options.filter({ hasText: "Via Shirur and Ahilyanagar" }).getByRole("button").first().click();
  await expect(stops).toContainText("Shirur");
  await expect(stops).not.toContainText("Sangamner");

  // A stop that is not on this road is refused with a reason.
  await pickPlace(page.getByRole("form", { name: "Add stop" }), "Add a stop", "Nashik");
  await page.getByRole("form", { name: "Add stop" }).getByRole("button", { name: "Add stop" }).click();
  await expect(page.getByTestId("toast").first()).toContainText("cannot be a stop");
  await expect(stops).not.toContainText("Nashik");

  // Remove a stop, add it back.
  await page.getByRole("button", { name: "Remove stop Shirur" }).click();
  await expect(stops).not.toContainText("Shirur");
  await pickPlace(page.getByRole("form", { name: "Add stop" }), "Add a stop", "Shirur");
  await page.getByRole("form", { name: "Add stop" }).getByRole("button", { name: "Add stop" }).click();
  await expect(stops).toContainText("Shirur");

  // Remove one road, then the service.
  await options.filter({ hasText: "Via Narayangaon and Sangamner" }).getByRole("button", { name: /^Remove Via/ }).click();
  await dialog(page).getByRole("button", { name: "Remove route option" }).click();
  await expect(options).toHaveCount(1);
  await removeServiceIfPresent(page, "Pune", "Shirdi");
});

test("a custom route option is built by choosing the towns the road passes through", async ({ page }) => {
  test.setTimeout(240_000);
  await signInAndWait(page, USERS.owner2);
  await removeServiceIfPresent(page, "Pune", "Nashik");

  await page.getByRole("button", { name: "New service" }).click();
  await pickPlace(dialog(page), "Origin", "Pune");
  await pickPlace(dialog(page), "Destination", "Nashik");
  await dialog(page).getByLabel(/Add 2 known route options/).uncheck();
  await dialog(page).getByRole("button", { name: "Create service" }).click();
  await expect(page.getByText("No route options yet")).toBeVisible();

  // The known corridors are still offered one by one.
  await expect(page.getByRole("region", { name: "Suggested route options" })).toContainText("Via Narayangaon and Sangamner");

  await page.getByRole("button", { name: "Add route option" }).click();
  const form = dialog(page).getByRole("form", { name: "New route option" });
  await pickPlace(form, "Add a town the road passes through", "Sangam", "Sangamner");
  await expect(form.getByRole("list", { name: "Route via" })).toContainText("Sangamner");
  await expect(form.getByLabel("Name")).toHaveAttribute("placeholder", "Via Sangamner");

  // Order can be changed, and a town can be removed.
  await pickPlace(form, "Add a town the road passes through", "Sinnar");
  await expect(form.getByRole("list", { name: "Route via" }).getByRole("listitem")).toHaveCount(2);
  await form.getByRole("button", { name: "Move Sinnar earlier" }).click();
  await expect(form.getByLabel("Name")).toHaveAttribute("placeholder", "Via Sinnar and Sangamner");
  await form.getByRole("button", { name: "Remove Sinnar" }).click();
  await expect(form.getByLabel("Name")).toHaveAttribute("placeholder", "Via Sangamner");

  await form.getByRole("button", { name: "Create route option" }).click();
  const option = page.getByTestId("route-option").filter({ hasText: "Via Sangamner" });
  await expect(option).toContainText("Ready", { timeout: 90_000 });
  await expect(option).toContainText("km");

  await removeServiceIfPresent(page, "Pune", "Nashik");
});
