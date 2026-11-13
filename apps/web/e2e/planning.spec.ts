import { expect, test, type Page } from "@playwright/test";

import { signInAndWait, USERS } from "./helpers";

const suffix = Date.now().toString().slice(-6);

async function addBooking(page: Page, count: string, pickup: string, drop: string) {
  const form = page.getByRole("form", { name: "Add booking" });
  await form.getByLabel("Passengers", { exact: true }).fill(count);
  await form.getByLabel("Pickup stop").fill(pickup);
  await form.getByLabel("Drop stop").fill(drop);
  await form.getByRole("button", { name: "Add booking" }).click();
  await expect(page.getByTestId("bookings-notice")).toContainText("Booking added");
}

test("operator takes a journey from draft to ready", async ({ page }) => {
  test.setTimeout(240_000);
  const origin = `Pune ${suffix}`;
  const registration = `PLN ${suffix}`;
  await signInAndWait(page, USERS.owner1);

  // Service with a route option and one intermediate stop.
  await page.goto("/dashboard/services");
  await page.getByLabel("Origin", { exact: true }).fill(origin);
  await page.getByLabel("Origin latitude").fill("18.5204");
  await page.getByLabel("Origin longitude").fill("73.8567");
  await page.getByLabel("Destination", { exact: true }).fill("Nanded");
  await page.getByLabel("Destination latitude").fill("19.1383");
  await page.getByLabel("Destination longitude").fill("77.321");
  await page.getByRole("button", { name: "Add service" }).click();
  await page.getByRole("row", { name: new RegExp(origin) }).getByRole("link", { name: "Route options" }).click();
  const newOption = page.getByRole("form", { name: "New route option" });
  await newOption.getByLabel("Route option name").fill("Via Ahmednagar and Beed");
  await newOption.getByLabel(/Via-points/).fill("Ahmednagar, 19.0948, 74.7496\nBeed, 18.9891, 75.7601");
  await newOption.getByRole("button", { name: "Create route option" }).click();
  await expect(page.getByTestId("routes-notice")).toContainText("Route option created", { timeout: 60_000 });
  const addStop = page.getByRole("form", { name: "Add stop" });
  await addStop.getByLabel("Stop name").fill("Beed");
  await addStop.getByLabel("Latitude").fill("18.9891");
  await addStop.getByLabel("Longitude").fill("75.7601");
  await addStop.getByRole("button", { name: "Add stop" }).click();
  await expect(page.getByRole("table", { name: "Route stops" }).getByRole("row", { name: /Beed/ })).toBeVisible();

  // Bus and journey.
  await page.goto("/dashboard/buses");
  await page.getByLabel("Registration").fill(registration);
  await page.getByRole("button", { name: "Add bus" }).click();
  await expect(page.getByRole("row", { name: new RegExp(registration) })).toBeVisible();
  await page.goto("/dashboard/journeys");
  const journeyForm = page.getByRole("form", { name: "New journey" });
  await journeyForm.getByRole("combobox", { name: "Service" }).selectOption({ label: `${origin} → Nanded` });
  await journeyForm.getByRole("combobox", { name: "Bus" }).selectOption({ label: `${registration} (40 seats)` });
  await journeyForm.getByLabel("Departure (IST)").fill("2031-05-01T22:00");
  await journeyForm.getByLabel("Scheduled arrival (IST)").fill("2031-05-02T07:30");
  await journeyForm.getByRole("button", { name: "Create journey" }).click();
  await page.getByRole("row", { name: new RegExp(origin) }).getByRole("link", { name: "Open" }).click();

  await page.getByRole("combobox", { name: "Route option" }).selectOption({ label: "Via Ahmednagar and Beed" });
  await page.getByRole("button", { name: "Use this route" }).click();
  await expect(page.getByTestId("journey-route")).toContainText("Via Ahmednagar and Beed");

  await addBooking(page, "3", origin, "Beed");
  await addBooking(page, "2", "Beed", "Nanded");
  await addBooking(page, "1", origin, "Latur");

  // A booking to a place that is not on this route is called out.
  await expect(page.getByTestId("unresolved-bookings")).toContainText("Latur");

  // Bookings give hints only: nothing is active until the operator ticks it.
  const plan = page.getByRole("table", { name: "Stop plan" });
  await expect(plan.getByRole("row", { name: /Beed/ })).toContainText("2 board, 3 alight");
  await expect(plan.getByLabel("Beed active")).not.toBeChecked();

  // Submitting an unconfirmed plan is blocked with reasons.
  await page.getByRole("button", { name: "Submit plan for confirmation" }).click();
  await expect(page.getByTestId("plan-error")).toContainText("problems");
  await expect(page.getByTestId("plan-blocking")).toContainText("Latur");

  // Cancel the stray booking, then confirm the stops with the booking numbers.
  await page.getByRole("table").filter({ hasText: "Reference" }).getByRole("row", { name: /Latur/ })
    .getByRole("button", { name: "Cancel booking" }).click();
  await expect(page.getByTestId("booked-passengers")).toHaveText("5 / 40");
  await plan.getByLabel(`${origin} active`).check();
  await plan.getByLabel("Beed active").check();
  await plan.getByLabel("Nanded active").check();
  await expect(plan.getByLabel(`${origin} pickup`)).toHaveValue("3");
  await page.getByRole("button", { name: "Confirm active stops" }).click();
  await expect(plan.getByLabel("Beed active")).toBeChecked();

  await page.getByRole("button", { name: "Check plan" }).click();
  await expect(page.getByTestId("plan-validation")).toContainText("The plan is consistent");

  await page.getByRole("button", { name: "Submit plan for confirmation" }).click();
  await expect(page.getByTestId("journey-summary")).toContainText("awaiting confirmation");
  await page.getByRole("button", { name: "Assign route" }).click();
  await expect(page.getByTestId("journey-summary")).toContainText("ready", { timeout: 60_000 });

  const versions = page.getByRole("table", { name: "Route versions" });
  await expect(versions.getByRole("row", { name: /v1/ })).toContainText("current");
  // Stops are locked once the journey is ready.
  await expect(plan.getByLabel("Beed active")).toBeDisabled();
});
