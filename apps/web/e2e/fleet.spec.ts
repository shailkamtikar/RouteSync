import { expect, test } from "@playwright/test";

import { signInAndWait, USERS } from "./helpers";

const suffix = Date.now().toString().slice(-6);

test("operator manages a bus: add, duplicate rejected, edit, remove", async ({ page }) => {
  const registration = `E2E ${suffix}`;
  await signInAndWait(page, USERS.owner1);
  await page.getByRole("link", { name: "Buses" }).click();
  await expect(page.getByRole("heading", { name: "Buses" })).toBeVisible();

  await page.getByLabel("Registration").fill(registration);
  await page.getByLabel("Capacity", { exact: true }).fill("36");
  await page.getByRole("button", { name: "Add bus" }).click();
  const row = page.getByRole("row", { name: new RegExp(registration) });
  await expect(row).toContainText("36");

  await page.getByLabel("Registration").fill(registration);
  await page.getByRole("button", { name: "Add bus" }).click();
  await expect(page.getByTestId("panel-error")).toContainText("already exists");

  await row.getByRole("button", { name: "Edit" }).click();
  await row.getByLabel(`Capacity for ${registration}`).fill("44");
  await row.getByRole("button", { name: "Save" }).click();
  await expect(row).toContainText("44");

  await row.getByRole("button", { name: "Remove" }).click();
  await expect(row).toHaveCount(0);
});

test("operator adds and removes a service; another operator cannot see it", async ({
  page,
  browser,
}) => {
  const origin = `Origin ${suffix}`;
  await signInAndWait(page, USERS.owner1);
  await page.getByRole("link", { name: "Services" }).click();
  await page.getByLabel("Origin", { exact: true }).fill(origin);
  await page.getByLabel("Destination", { exact: true }).fill("Nanded");
  await page.getByRole("button", { name: "Add service" }).click();
  const row = page.getByRole("row", { name: new RegExp(origin) });
  await expect(row).toBeVisible();

  const otherContext = await browser.newContext();
  const otherPage = await otherContext.newPage();
  await signInAndWait(otherPage, USERS.owner2);
  await otherPage.goto("/dashboard/services");
  await expect(otherPage.getByRole("heading", { name: "Services" })).toBeVisible();
  await expect(otherPage.getByText("Loading services…")).toHaveCount(0);
  await expect(otherPage.getByText(origin)).toHaveCount(0);
  await otherContext.close();

  await row.getByRole("button", { name: "Remove" }).click();
  await expect(row).toHaveCount(0);
});
