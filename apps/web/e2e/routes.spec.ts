import { expect, test } from "@playwright/test";

import { signInAndWait, USERS } from "./helpers";

const suffix = Date.now().toString().slice(-6);

test("operator defines two route options with route-specific stops and assigns one", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const origin = `Pune ${suffix}`;
  const registration = `RTE ${suffix}`;
  await signInAndWait(page, USERS.owner1);

  await page.goto("/dashboard/services");
  await page.getByLabel("Origin", { exact: true }).fill(origin);
  await page.getByLabel("Origin latitude").fill("18.5204");
  await page.getByLabel("Origin longitude").fill("73.8567");
  await page.getByLabel("Destination", { exact: true }).fill("Nanded");
  await page.getByLabel("Destination latitude").fill("19.1383");
  await page.getByLabel("Destination longitude").fill("77.321");
  await page.getByRole("button", { name: "Add service" }).click();
  await page
    .getByRole("row", { name: new RegExp(origin) })
    .getByRole("link", { name: "Route options" })
    .click();
  await expect(page.getByRole("heading", { name: /route options/ })).toBeVisible();

  const options = page.getByRole("table", { name: "Route options" });
  const newOption = page.getByRole("form", { name: "New route option" });

  await newOption.getByLabel("Route option name").fill("Via Ahmednagar and Beed");
  await newOption.getByLabel(/Via-points/).fill("Ahmednagar, 19.0948, 74.7496\nBeed, 18.9891, 75.7601");
  await newOption.getByRole("button", { name: "Create route option" }).click();
  await expect(page.getByTestId("routes-notice")).toContainText("Route option created", {
    timeout: 60_000,
  });
  await expect(options.getByRole("row", { name: /Via Ahmednagar and Beed/ })).toContainText("ready");

  await newOption.getByLabel("Route option name").fill("Via Solapur and Latur");
  await newOption.getByLabel(/Via-points/).fill("Solapur, 17.6599, 75.9064\nLatur, 18.4088, 76.5604");
  await newOption.getByRole("button", { name: "Create route option" }).click();
  await expect(options.getByRole("row", { name: /Via Solapur and Latur/ })).toContainText("ready", {
    timeout: 60_000,
  });

  // A malformed via-point line is caught before anything is sent.
  await newOption.getByLabel("Route option name").fill("Broken");
  await newOption.getByLabel(/Via-points/).fill("Beed, north, east");
  await newOption.getByRole("button", { name: "Create route option" }).click();
  await expect(page.getByTestId("routes-error")).toContainText("line 1");

  // Latur can be added to the southern option...
  const stops = page.getByRole("table", { name: "Route stops" });
  const addStop = page.getByRole("form", { name: "Add stop" });
  await expect(page.getByRole("heading", { name: /Stops on “Via Solapur and Latur”/ })).toBeVisible();
  await addStop.getByLabel("Stop name").fill("Latur");
  await addStop.getByLabel("Latitude").fill("18.4088");
  await addStop.getByLabel("Longitude").fill("76.5604");
  await addStop.getByRole("button", { name: "Add stop" }).click();
  await expect(stops.getByRole("row", { name: /Latur/ })).toContainText("Passenger stop");

  // ...but not to the northern option, which does not pass it.
  await options
    .getByRole("row", { name: /Via Ahmednagar and Beed/ })
    .getByRole("button", { name: "Show" })
    .click();
  await expect(page.getByRole("heading", { name: /Stops on “Via Ahmednagar and Beed”/ })).toBeVisible();
  await expect(stops.getByRole("row", { name: /Latur/ })).toHaveCount(0);
  await addStop.getByLabel("Stop name").fill("Latur");
  await addStop.getByLabel("Latitude").fill("18.4088");
  await addStop.getByLabel("Longitude").fill("76.5604");
  await addStop.getByRole("button", { name: "Add stop" }).click();
  await expect(page.getByTestId("routes-error")).toContainText("cannot be a stop");
  await expect(stops.getByRole("row", { name: /Latur/ })).toHaveCount(0);

  await addStop.getByLabel("Stop name").fill("Beed");
  await addStop.getByLabel("Latitude").fill("18.9891");
  await addStop.getByLabel("Longitude").fill("75.7601");
  await addStop.getByRole("button", { name: "Add stop" }).click();
  await expect(stops.getByRole("row", { name: /Beed/ })).toBeVisible();
  await expect(stops.getByRole("row").nth(1)).toContainText(origin);

  // The map shows OpenStreetMap attribution.
  await expect(page.getByRole("link", { name: /OpenStreetMap contributors/ }).first()).toBeVisible();

  // Assign the northern option to a new journey.
  await page.goto("/dashboard/buses");
  await page.getByLabel("Registration").fill(registration);
  await page.getByRole("button", { name: "Add bus" }).click();
  await expect(page.getByRole("row", { name: new RegExp(registration) })).toBeVisible();
  await page.goto("/dashboard/journeys");
  const journeyForm = page.getByRole("form", { name: "New journey" });
  await journeyForm.getByRole("combobox", { name: "Service" }).selectOption({ label: `${origin} → Nanded` });
  await journeyForm.getByRole("combobox", { name: "Bus" }).selectOption({ label: `${registration} (40 seats)` });
  await journeyForm.getByLabel("Departure (IST)").fill("2031-04-01T22:00");
  await journeyForm.getByLabel("Scheduled arrival (IST)").fill("2031-04-02T07:30");
  await journeyForm.getByRole("button", { name: "Create journey" }).click();
  await page.getByRole("row", { name: new RegExp(origin) }).getByRole("link", { name: "Open" }).click();

  await expect(page.getByTestId("journey-route")).toContainText("No route option chosen yet");
  await page.getByRole("combobox", { name: "Route option" }).selectOption({ label: "Via Ahmednagar and Beed" });
  await page.getByRole("button", { name: "Use this route" }).click();
  await expect(page.getByTestId("journey-route")).toContainText("Via Ahmednagar and Beed");
});
