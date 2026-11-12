import { expect, test } from "@playwright/test";

import { signInAndWait, USERS } from "./helpers";

const suffix = Date.now().toString().slice(-6);
const CSV_HEADER = "reference,contact_name,passenger_count,pickup_stop,drop_stop\n";

test("operator creates a journey and manages its bookings", async ({ page }) => {
  const registration = `JRN ${suffix}`;
  const origin = `Pune ${suffix}`;
  await signInAndWait(page, USERS.owner1);

  await page.goto("/dashboard/buses");
  await page.getByLabel("Registration").fill(registration);
  await page.getByLabel("Capacity", { exact: true }).fill("36");
  await page.getByRole("button", { name: "Add bus" }).click();
  await expect(page.getByRole("row", { name: new RegExp(registration) })).toBeVisible();

  await page.goto("/dashboard/services");
  await page.getByLabel("Origin", { exact: true }).fill(origin);
  await page.getByLabel("Destination", { exact: true }).fill("Nanded");
  await page.getByRole("button", { name: "Add service" }).click();
  await expect(page.getByRole("row", { name: new RegExp(origin) })).toBeVisible();

  await page.getByRole("link", { name: "Journeys" }).click();
  await expect(page.getByRole("heading", { name: "Journeys" })).toBeVisible();
  const form = page.getByRole("form", { name: "New journey" });
  await form.getByRole("combobox", { name: "Service" }).selectOption({ label: `${origin} → Nanded` });
  await form.getByRole("combobox", { name: "Bus" }).selectOption({ label: `${registration} (36 seats)` });
  await page.getByLabel("Departure (IST)").fill("2031-03-01T22:00");
  await page.getByLabel("Scheduled arrival (IST)").fill("2031-03-02T07:30");
  await page.getByRole("button", { name: "Create journey" }).click();
  const row = page.getByRole("row", { name: new RegExp(origin) });
  await expect(row).toContainText("1 Mar 2031, 22:00");
  await expect(row).toContainText("draft");

  // The same bus cannot be double-booked for overlapping times.
  await form.getByRole("combobox", { name: "Service" }).selectOption({ label: `${origin} → Nanded` });
  await form.getByRole("combobox", { name: "Bus" }).selectOption({ label: `${registration} (36 seats)` });
  await page.getByLabel("Departure (IST)").fill("2031-03-02T01:00");
  await page.getByLabel("Scheduled arrival (IST)").fill("2031-03-02T09:00");
  await page.getByRole("button", { name: "Create journey" }).click();
  await expect(page.getByTestId("panel-error")).toContainText("overlaps");

  await row.getByRole("link", { name: "Open" }).click();
  await expect(page.getByTestId("journey-summary")).toContainText("2 Mar 2031, 07:30");
  await expect(page.getByTestId("booked-passengers")).toHaveText("0 / 36");

  await page.getByLabel("Contact name").fill("Test Contact");
  await page.getByLabel("Passengers", { exact: true }).fill("2");
  await page.getByLabel("Pickup stop").fill("Pune");
  await page.getByLabel("Drop stop").fill("Nanded");
  await page.getByRole("button", { name: "Add booking" }).click();
  await expect(page.getByTestId("bookings-notice")).toContainText("Booking added");
  await expect(page.getByTestId("booked-passengers")).toHaveText("2 / 36");

  // A file with one bad row imports nothing and names the line.
  await page.getByLabel("Import CSV").setInputFiles({
    name: "bad.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(`${CSV_HEADER}A1,,1,Pune,Beed\nA2,,=1+1,Pune,Beed\n`),
  });
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await expect(page.getByText(/Line 3:/)).toBeVisible();
  await expect(page.getByTestId("booked-passengers")).toHaveText("2 / 36");

  await page.getByLabel("Import CSV").setInputFiles({
    name: "good.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(`${CSV_HEADER}A1,,1,Pune,Beed\nA2,,3,Beed,Nanded\n`),
  });
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await expect(page.getByTestId("bookings-notice")).toContainText("Bookings imported");
  await expect(page.getByTestId("booked-passengers")).toHaveText("6 / 36");

  await page
    .getByRole("row", { name: /A2/ })
    .getByRole("button", { name: "Cancel booking" })
    .click();
  await expect(page.getByTestId("booked-passengers")).toHaveText("3 / 36");
});

test("another operator cannot open the journey by its address", async ({ page, browser }) => {
  await signInAndWait(page, USERS.owner1);
  await page.goto("/dashboard/journeys");
  const href = await page.getByRole("link", { name: "Open" }).first().getAttribute("href");
  expect(href).toBeTruthy();

  const otherContext = await browser.newContext();
  const otherPage = await otherContext.newPage();
  await signInAndWait(otherPage, USERS.owner2);
  await otherPage.goto(href!);
  await expect(otherPage.getByText("Journey not found.")).toBeVisible();
  await otherContext.close();
});
