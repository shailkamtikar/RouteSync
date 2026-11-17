import { expect, test } from "@playwright/test";

import { createDemoJourney } from "./demo";
import { dialog, futureLocal, signInAndWait, USERS } from "./helpers";

const suffix = Date.now().toString().slice(-6);
const CSV_HEADER = "reference,contact_name,passenger_count,pickup_stop,drop_stop\n";

test("operator takes a journey from draft to ready", async ({ page }) => {
  test.setTimeout(300_000);
  createDemoJourney("ready"); // makes sure the Pune to Nanded service and its route options exist
  const registration = `PLN ${suffix}`;
  await signInAndWait(page, USERS.owner2);

  await page.goto("/dashboard/buses");
  await page.getByRole("button", { name: "Add bus" }).click();
  await dialog(page).getByLabel("Registration").fill(registration);
  await dialog(page).getByRole("button", { name: "Add bus" }).click();
  await expect(page.getByTestId("bus-card").filter({ hasText: registration })).toBeVisible();

  await page.goto("/dashboard/journeys");
  await page.getByRole("button", { name: "New journey" }).click();
  const form = dialog(page).getByRole("form", { name: "New journey" });
  await form.getByLabel("Service").selectOption({ label: "Pune → Nanded" });
  await form.getByLabel("Bus").selectOption({ label: `${registration} · 40 seats` });
  await form.getByLabel("Departure (IST)").fill(futureLocal(21));
  await form.getByRole("button", { name: "Create journey" }).click();
  await expect(page.getByTestId("journey-route")).toContainText("Via Ahilyanagar, Beed and Parbhani");

  // The route can be changed while the journey is a draft, and changed back.
  const choices = page.getByRole("radiogroup", { name: "Route options" });
  await choices.getByRole("radio", { name: /Via Baramati, Barshi and Latur/ }).click();
  await expect(page.getByTestId("journey-route")).toContainText("Via Baramati, Barshi and Latur");
  await choices.getByRole("radio", { name: /Via Ahilyanagar, Beed and Parbhani/ }).click();
  await expect(page.getByTestId("journey-route")).toContainText("Via Ahilyanagar, Beed and Parbhani");

  // Bookings: one of them goes to a place that is not on this route.
  await page.getByRole("tab", { name: /Bookings/ }).click();
  await page.getByText("Import bookings from a CSV file").click();
  await page.getByLabel("CSV file").setInputFiles({
    name: "plan.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(`${CSV_HEADER}P1,,3,Pune,Beed\nP2,,2,Beed,Nanded\nP3,,1,Pune,Latur\n`),
  });
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await expect(page.getByTestId("booked-passengers")).toHaveText("6 / 40");

  await page.getByRole("tab", { name: "Route and stops" }).click();
  await expect(page.getByTestId("unresolved-bookings")).toContainText("Latur");

  // Bookings give hints only: nothing is active until the operator ticks it.
  const plan = page.getByRole("table", { name: "Stop plan" });
  await expect(plan.getByRole("row", { name: /Beed/ })).toContainText("2 board, 3 alight");
  await expect(plan.getByLabel("Beed active")).not.toBeChecked();

  // Submitting an unconfirmed plan is blocked, with the reasons listed.
  await page.getByTestId("primary-action").click();
  await expect(dialog(page)).toContainText("The plan needs attention");
  await expect(dialog(page)).toContainText("Latur");
  await dialog(page).getByRole("button", { name: "Got it" }).click();

  // Cancel the stray booking, then confirm the stops with the booking numbers.
  await page.getByRole("tab", { name: /Bookings/ }).click();
  await page.getByRole("button", { name: "Cancel booking P3" }).click();
  await expect(page.getByTestId("booked-passengers")).toHaveText("5 / 40");
  await page.getByRole("tab", { name: "Route and stops" }).click();
  await plan.getByLabel("Pune active").check();
  await plan.getByLabel("Beed active").check();
  await plan.getByLabel("Nanded active").check();
  await expect(plan.getByLabel("Pune pickup")).toHaveValue("3");
  await page.getByRole("button", { name: "Confirm active stops" }).click();
  await expect(plan.getByLabel("Beed active")).toBeChecked();

  await page.getByRole("button", { name: "Check plan" }).click();
  await expect(page.getByTestId("plan-validation")).toContainText("The plan is consistent");

  // The header offers exactly the next step each time.
  await expect(page.getByTestId("primary-action")).toHaveText("Submit plan");
  await page.getByTestId("primary-action").click();
  await expect(page.getByTestId("journey-summary")).toContainText("Awaiting confirmation");
  await expect(page.getByTestId("primary-action")).toHaveText("Assign route");
  await page.getByTestId("primary-action").click();
  await expect(page.getByTestId("journey-summary")).toContainText("Ready", { timeout: 90_000 });
  await expect(page.getByTestId("primary-action")).toHaveText("Publish");

  const versions = page.getByRole("table", { name: "Route versions" });
  await expect(versions.getByRole("row", { name: /v1/ })).toContainText("current");
  // Stops are locked once the journey is ready.
  await expect(plan.getByLabel("Beed active")).toBeDisabled();

  // Publish and open the passenger link.
  await page.getByTestId("primary-action").click();
  await expect(page.getByTestId("journey-summary")).toContainText("Published");
  await page.getByRole("tab", { name: "Passenger link" }).click();
  await page.getByRole("button", { name: "Create link" }).click();
  const link = page.getByTestId("tracking-url").getByLabel("Passenger link");
  await expect(link).toHaveValue(/\/track\/.+/);
});

test("the progress steps follow the journey and the monitor is one click away", async ({ page }) => {
  test.setTimeout(240_000);
  const demo = createDemoJourney("published");
  await signInAndWait(page, USERS.owner2);
  await page.goto(`/dashboard/journeys/${demo.journey_id}`);
  const steps = page.getByRole("region", { name: "Journey progress" });
  await expect(steps.locator("li[data-state='done']")).toHaveCount(3); // plan, confirm, ready
  await expect(steps.locator("li[data-state='current']")).toContainText("Published");
  await expect(page.getByTestId("primary-action")).toHaveText("Start boarding");
  // After departure the booking form is gone, and the monitor is one click away.
  await page.getByRole("tab", { name: /Bookings/ }).click();
  await expect(page.getByRole("form", { name: "Add booking" })).toBeVisible();
  await page.getByRole("link", { name: "Live monitor" }).click();
  await expect(page).toHaveURL(/\/monitor$/);
});
