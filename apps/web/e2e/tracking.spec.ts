import { expect, test } from "@playwright/test";

import { API, createDemoJourney, gpsPoint } from "./demo";
import { signInAndWait, USERS } from "./helpers";

test("passengers follow a journey on the public page", async ({ page, request, context }) => {
  test.setTimeout(300_000);
  const demo = createDemoJourney("boarding");
  expect(demo.tracking_url).toBeTruthy();
  const device = { Authorization: `Bearer ${demo.device_token}` };

  // Before departure: plan-based times, no live position.
  await page.goto(demo.tracking_url!);
  await expect(page.getByTestId("journey-status")).toContainText("Boarding");
  await expect(page.getByTestId("next-stop-card")).toContainText("Pune");
  await expect(page.getByTestId("destination-card")).toContainText("Nanded");
  await expect(page.getByTestId("stale-banner")).toContainText("No live position");
  await expect(page.getByTestId("promise")).toContainText("Arrival promised at booking");
  const timeline = page.getByTestId("timeline");
  await expect(timeline.locator("li")).toHaveCount(3); // Pune, Beed, Nanded
  await expect(page.getByRole("link", { name: /OpenStreetMap contributors/ }).first()).toBeVisible();

  // Nothing private is in the page.
  const html = await page.content();
  for (const secret of ["passenger_count", "reference", "contact_name", "booking_id", "seat"]) {
    expect(html).not.toContain(secret);
  }

  // The bus departs: operator records Pune, device sends a fresh position.
  const operator = await context.newPage();
  await signInAndWait(operator, USERS.owner1);
  await operator.goto(demo.monitor_url);
  const events = operator.getByRole("table", { name: "Stop events" });
  const pune = events.getByRole("row", { name: /Pune/ });
  await pune.getByRole("button", { name: "Arrived" }).click();
  await pune.getByRole("button", { name: "Departed" }).click();
  await expect(operator.getByTestId("monitor-status")).toHaveText("in progress");
  const sent = await request.post(`${API}/api/v1/ingest/gps`, {
    headers: device,
    data: { points: [gpsPoint(19.0948, 74.7496)] },
  });
  expect(sent.status()).toBe(202);

  await expect(page.getByTestId("journey-status")).toContainText("On the way", { timeout: 25_000 });
  await expect(page.getByTestId("next-stop-card")).toContainText("Beed", { timeout: 25_000 });
  await expect(page.getByTestId("stale-banner")).toHaveCount(0, { timeout: 25_000 });
  await expect(timeline.locator("li[data-status='completed']")).toHaveCount(1);
  await expect(timeline.locator("li[data-status='next']")).toContainText("Beed");
  await expect(page.getByRole("img", { name: "Bus" })).toBeVisible();
  await expect(page.getByTestId("progress")).toContainText("remaining");

  // Counts are hidden until the operator allows them.
  await expect(page.getByText(/boarding, .* alighting/)).toHaveCount(0);
  await operator.goto(`/dashboard/journeys/${demo.journey_id}`);
  await operator.getByLabel("Show passenger counts on the public page").click();
  await expect(operator.getByLabel("Show passenger counts on the public page")).toBeChecked();
  await page.reload();
  await expect(timeline).toContainText("boarding", { timeout: 20_000 });

  // The link is revoked: the page says so and shows no journey data.
  await operator.getByRole("button", { name: "Revoke link" }).click();
  await expect(operator.getByTestId("link-status")).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("link-unavailable")).toContainText("no longer active");
  await expect(page.getByText("Nanded")).toHaveCount(0);
});

test("an unknown link shows no information", async ({ page }) => {
  await page.goto("/track/not-a-real-token");
  await expect(page.getByTestId("link-unavailable")).toContainText("not recognised");
});

test("public page works at phone width", async ({ page }) => {
  test.setTimeout(200_000);
  const demo = createDemoJourney("boarding");
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(demo.tracking_url!);
  await expect(page.getByTestId("next-stop-card")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(overflow).toBe(false);
});
