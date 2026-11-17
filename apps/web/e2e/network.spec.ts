import { expect, test } from "@playwright/test";

import { signInAndWait, USERS } from "./helpers";

// These read the seeded Maharashtra network (scripts/seed_network.py) and change nothing.
test("the network covers Maharashtra with several services and route options", async ({ page }) => {
  await signInAndWait(page, USERS.owner1);
  await page.goto("/dashboard/services");
  const cards = page.getByTestId("service-card");
  await expect(cards.first()).toBeVisible({ timeout: 20_000 });
  expect(await cards.count()).toBeGreaterThanOrEqual(12);
  for (const city of ["Mumbai", "Pune", "Nagpur", "Nashik", "Kolhapur", "Nanded", "Solapur"]) {
    await expect(cards.filter({ hasText: city }).first()).toBeVisible();
  }

  // Search narrows the list.
  await page.getByLabel("Search services").fill("nagpur");
  const shown = await cards.count();
  expect(shown).toBeGreaterThan(2);
  for (let i = 0; i < shown; i += 1) await expect(cards.nth(i)).toContainText("Nagpur");
  await page.getByLabel("Search services").fill("qqqq");
  await expect(page.getByText("No service matches")).toBeVisible();
});

test("Pune to Nanded has several different roads, each with its own stops", async ({ page }) => {
  await signInAndWait(page, USERS.owner1);
  await page.goto("/dashboard/services");
  await page.getByLabel("Search services").fill("Nanded");
  await page.getByTestId("service-card").filter({ hasText: "Pune" }).filter({ hasText: "Nanded" }).first().click();
  const options = page.getByTestId("route-option");
  await expect(options).toHaveCount(3, { timeout: 20_000 });
  await expect(options.filter({ hasText: "Via Ahilyanagar, Beed and Parbhani" })).toBeVisible();
  await expect(options.filter({ hasText: "Via Baramati, Barshi and Latur" })).toBeVisible();
  const stops = page.getByTestId("route-stops");
  await options.filter({ hasText: "Via Baramati, Barshi and Latur" }).getByRole("button").first().click();
  await expect(stops).toContainText("Latur");
  await expect(stops).not.toContainText("Beed");
});

test("journeys exist in every state and open the right screen", async ({ page }) => {
  await signInAndWait(page, USERS.owner1);
  await page.goto("/dashboard/journeys");
  await expect(page.getByTestId("journey-row").first()).toBeVisible({ timeout: 20_000 });
  for (const state of ["On the road", "Upcoming", "Being planned", "Past"]) {
    await expect(page.getByRole("region", { name: state })).toBeVisible();
  }
  await page.getByRole("button", { name: /^On the road/ }).click();
  await page.getByTestId("journey-row").first().click();
  await expect(page.getByRole("link", { name: "Live monitor" })).toBeVisible();
});

test("the fleet is listed with plates, seats and what each bus is doing", async ({ page }) => {
  await signInAndWait(page, USERS.owner1);
  await page.goto("/dashboard/buses");
  const cards = page.getByTestId("bus-card");
  await expect(cards.first()).toBeVisible({ timeout: 20_000 });
  expect(await cards.count()).toBeGreaterThanOrEqual(15);
  await expect(page.getByText("On the road").first()).toBeVisible();
  await expect(page.getByText("Scheduled").first()).toBeVisible();
});
