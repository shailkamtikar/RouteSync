import { expect, test, type Page } from "@playwright/test";

import { createDemoJourney } from "./demo";
import { dialog, futureLocal, nav, signInAndWait, USERS } from "./helpers";

const suffix = Date.now().toString().slice(-6);
const CSV_HEADER = "reference,contact_name,passenger_count,pickup_stop,drop_stop\n";

async function addBus(page: Page, registration: string, seats: string) {
  await page.goto("/dashboard/buses");
  await page.getByRole("button", { name: "Add bus" }).click();
  await dialog(page).getByLabel("Registration").fill(registration);
  await dialog(page).getByLabel("Seats").fill(seats);
  await dialog(page).getByRole("button", { name: "Add bus" }).click();
  await expect(page.getByTestId("bus-card").filter({ hasText: registration })).toBeVisible();
}

async function newJourney(page: Page, registration: string, seats: string, departure: string) {
  await page.getByRole("button", { name: "New journey" }).click();
  const form = dialog(page).getByRole("form", { name: "New journey" });
  await form.getByLabel("Service").selectOption({ label: "Pune → Nanded" });
  await form.getByLabel("Bus").selectOption({ label: `${registration} · ${seats} seats` });
  await form.getByLabel("Departure (IST)").fill(departure);
  return form;
}

test("operator creates a journey and manages its bookings", async ({ page }) => {
  test.setTimeout(300_000);
  createDemoJourney("ready"); // makes sure the Pune to Nanded service and its route options exist
  const registration = `JRN ${suffix}`;
  await signInAndWait(page, USERS.owner2);
  await addBus(page, registration, "36");

  await nav(page).getByRole("link", { name: "Journeys" }).click();
  await expect(page.getByRole("heading", { name: "Journeys" })).toBeVisible();
  const departure = futureLocal(22);
  const form = await newJourney(page, registration, "36", departure);
  // A ready route option is chosen for the operator and the arrival is estimated from its drive time.
  await expect(form.getByLabel("Route option")).toContainText("Via Ahilyanagar, Beed and Parbhani");
  await expect(form.getByLabel("Scheduled arrival (IST)")).not.toHaveValue("");
  await form.getByRole("button", { name: "Create journey" }).click();

  await expect(page).toHaveURL(/\/dashboard\/journeys\/[0-9a-f-]+$/);
  await expect(page.getByTestId("journey-summary")).toContainText("Draft");
  await expect(page.getByTestId("journey-route")).toContainText("Via Ahilyanagar, Beed and Parbhani");
  await expect(page.getByTestId("booked-passengers")).toHaveText("0 / 36");
  const journeyUrl = page.url();

  // The same bus cannot be double-booked for overlapping times.
  await page.goto("/dashboard/journeys");
  const again = await newJourney(page, registration, "36", departure);
  await again.getByRole("button", { name: "Create journey" }).click();
  await expect(dialog(page).getByRole("alert")).toContainText("overlaps");
  await dialog(page).getByRole("button", { name: "Cancel" }).click();

  await page.goto(journeyUrl);
  await page.getByRole("tab", { name: /Bookings/ }).click();
  const booking = page.getByRole("form", { name: "Add booking" });
  await booking.getByLabel("Contact name").fill("Test Contact");
  await booking.getByLabel("Passengers", { exact: true }).fill("2");
  await booking.getByLabel("Pickup stop").selectOption("Pune");
  // The drop list only offers stops after the pickup.
  await expect(booking.getByLabel("Drop stop").locator("option", { hasText: "Pune" })).toHaveCount(0);
  await booking.getByLabel("Drop stop").selectOption("Nanded");
  await booking.getByRole("button", { name: "Add booking" }).click();
  await expect(page.getByTestId("toast").first()).toContainText("Booking added");
  await expect(page.getByTestId("booked-passengers")).toHaveText("2 / 36");
  await expect(page.getByRole("progressbar", { name: "Seats booked" })).toHaveAttribute("aria-valuenow", "6");

  // A file with one bad row imports nothing and names the line.
  await page.getByText("Import bookings from a CSV file").click();
  await page.getByLabel("CSV file").setInputFiles({
    name: "bad.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(`${CSV_HEADER}A1,,1,Pune,Beed\nA2,,=1+1,Pune,Beed\n`),
  });
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await expect(page.getByText(/Line 3:/)).toBeVisible();
  await expect(page.getByTestId("booked-passengers")).toHaveText("2 / 36");

  await page.getByLabel("CSV file").setInputFiles({
    name: "good.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(`${CSV_HEADER}A1,,1,Pune,Beed\nA2,,3,Beed,Nanded\n`),
  });
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await expect(page.getByTestId("toast").first()).toContainText("Bookings imported");
  await expect(page.getByTestId("booked-passengers")).toHaveText("6 / 36");

  await page.getByRole("button", { name: "Cancel booking A2" }).click();
  await expect(page.getByTestId("booked-passengers")).toHaveText("3 / 36");
  // Cancelled bookings are hidden until asked for.
  await expect(page.getByRole("row", { name: /A2/ })).toHaveCount(0);
  await page.getByLabel("Show cancelled bookings").check();
  await expect(page.getByRole("row", { name: /A2/ })).toContainText("cancelled");
});

test("a draft journey can change its bus and the list can be filtered", async ({ page }) => {
  test.setTimeout(300_000);
  createDemoJourney("ready");
  const first = `CHG ${suffix}`;
  const second = `CHH ${suffix}`;
  await signInAndWait(page, USERS.owner2);
  await addBus(page, first, "40");
  await addBus(page, second, "45");

  await page.goto("/dashboard/journeys");
  const form = await newJourney(page, first, "40", futureLocal(6));
  await form.getByRole("button", { name: "Create journey" }).click();
  await expect(page.getByTestId("journey-summary")).toContainText(first);
  const url = page.url();

  await page.getByRole("button", { name: "Change bus" }).click();
  await dialog(page).getByRole("combobox", { name: "Bus" }).selectOption({ label: `${second} · 45 seats` });
  await dialog(page).getByRole("button", { name: "Change bus" }).click();
  await expect(page.getByTestId("journey-summary")).toContainText(second);
  await expect(page.getByTestId("booked-passengers")).toHaveText("0 / 45");

  // Filters and search on the list.
  await page.goto("/dashboard/journeys");
  await page.getByLabel("Search journeys").fill(second);
  await expect(page.getByTestId("journey-row")).toHaveCount(1);
  await page.getByRole("button", { name: /^Planning/ }).click();
  await expect(page.getByTestId("journey-row")).toHaveCount(1);
  await page.getByRole("button", { name: /^On the road/ }).click();
  await expect(page.getByTestId("journey-row")).toHaveCount(0);
  await expect(page.getByText("Nothing matches")).toBeVisible();
  await page.getByRole("button", { name: /^All/ }).click();
  await page.getByTestId("journey-row").click();
  await expect(page).toHaveURL(url);
});

test("another operator cannot open the journey by its address", async ({ page }) => {
  test.setTimeout(240_000);
  const demo = createDemoJourney("boarding");
  await signInAndWait(page, USERS.owner1);
  await page.goto(`/dashboard/journeys/${demo.journey_id}`);
  await expect(page.getByRole("heading", { name: "Journey not found" })).toBeVisible();
  await page.goto(`/dashboard/journeys/${demo.journey_id}/monitor`);
  await expect(page.getByRole("heading", { name: "Journey not found" })).toBeVisible();
});

test("a draft journey can be cancelled after confirmation", async ({ page }) => {
  test.setTimeout(240_000);
  createDemoJourney("ready");
  const registration = `CNL ${suffix}`;
  await signInAndWait(page, USERS.owner2);
  await addBus(page, registration, "32");
  await page.goto("/dashboard/journeys");
  const form = await newJourney(page, registration, "32", futureLocal(9));
  await form.getByRole("button", { name: "Create journey" }).click();
  await page.getByRole("button", { name: "Cancel journey" }).click();
  await dialog(page).getByRole("button", { name: "Keep it" }).click();
  await expect(page.getByTestId("journey-summary")).toContainText("Draft");
  await page.getByRole("button", { name: "Cancel journey" }).click();
  await dialog(page).getByRole("button", { name: "Cancel journey" }).click();
  await expect(page.getByText("This journey was cancelled.")).toBeVisible();
});
