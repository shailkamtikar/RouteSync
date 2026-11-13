import { expect, test } from "@playwright/test";

import { API, createDemoJourney, gpsPoint } from "./demo";
import { signInAndWait, USERS } from "./helpers";

test("operator monitors a running journey", async ({ page, request }) => {
  test.setTimeout(300_000);
  const demo = createDemoJourney("boarding");
  const device = { Authorization: `Bearer ${demo.device_token}` };

  await signInAndWait(page, USERS.owner1);
  await page.goto(`/dashboard/journeys/${demo.journey_id}/monitor`);
  await expect(page.getByTestId("monitor-status")).toHaveText("boarding");

  // Before any position: the ETA is plan-based and three cards are shown.
  await expect(page.getByTestId("next-stop-card")).toContainText("Pune");
  await expect(page.getByTestId("destination-card")).toContainText("Nanded");
  await expect(page.getByTestId("commitment-card")).toContainText("Promised at booking");
  await expect(page.getByTestId("onboard-card")).toContainText("planned");

  // Record what happens at the origin.
  const events = page.getByRole("table", { name: "Stop events" });
  const pune = events.getByRole("row", { name: /Pune/ });
  await pune.getByRole("button", { name: "Arrived" }).click();
  await pune.getByLabel("Passenger count at Pune").fill("5");
  await pune.getByRole("button", { name: "Boarded" }).click();
  await expect(page.getByTestId("onboard-card")).toContainText("from recorded boardings");
  await expect(page.getByTestId("onboard-card").locator("strong")).toHaveText("5");
  await pune.getByRole("button", { name: "Departed" }).click();
  await expect(page.getByTestId("monitor-status")).toHaveText("in progress");
  await expect(pune).toContainText("departed");

  // A stop cannot be skipped: Nanded before Beed is refused.
  await events.getByRole("row", { name: /Nanded/ }).getByRole("button", { name: "Arrived" }).click();
  await expect(page.getByTestId("monitor-error")).toContainText("Beed");

  // The device reports a fresh position near Ahmednagar.
  const fresh = await request.post(`${API}/api/v1/ingest/gps`, {
    headers: device,
    data: { points: [gpsPoint(19.0948, 74.7496)] },
  });
  expect(fresh.status()).toBe(202);
  expect((await fresh.json()).accepted).toBe(1);
  await expect(page.getByTestId("next-stop-card")).toContainText("Beed", { timeout: 20_000 });
  await expect(page.getByTestId("stale-banner")).toHaveCount(0);
  await expect(page.getByRole("img", { name: "Bus" })).toBeVisible();

  // Manual mode can be switched on.
  await page.getByLabel(/Manual mode/).click();
  await expect(page.getByLabel(/Manual mode/)).toBeChecked();

  // A simulated slowdown ahead is labelled as simulated.
  const incident = page.getByRole("form", { name: "Add simulated incident" });
  await incident.getByLabel("From km").fill("200");
  await incident.getByLabel("To km").fill("230");
  await incident.getByRole("button", { name: "Add incident" }).click();
  await expect(page.getByRole("list", { name: "Active incidents" })).toContainText("Simulated slowdown");
  await expect(page.getByTestId("monitor-alerts")).toContainText("Simulated slow traffic", { timeout: 20_000 });
});

test("monitor shows when the position is not live, and hides other operators' journeys", async ({
  page,
  request,
  browser,
}) => {
  test.setTimeout(300_000);
  const demo = createDemoJourney("boarding");
  // A position that is already ten minutes old.
  const old = await request.post(`${API}/api/v1/ingest/gps`, {
    headers: { Authorization: `Bearer ${demo.device_token}` },
    data: { points: [gpsPoint(18.5204, 73.8567, 600)] },
  });
  expect(old.status()).toBe(202);

  await signInAndWait(page, USERS.owner1);
  await page.goto(`/dashboard/journeys/${demo.journey_id}/monitor`);
  await expect(page.getByTestId("stale-banner")).toContainText("Location not live");
  await expect(page.getByRole("img", { name: "Bus (location not live)" })).toBeVisible();

  const otherContext = await browser.newContext();
  const otherPage = await otherContext.newPage();
  await signInAndWait(otherPage, USERS.owner2);
  await otherPage.goto(`/dashboard/journeys/${demo.journey_id}/monitor`);
  await expect(otherPage.getByText("Journey not found.")).toBeVisible();
  await otherContext.close();
});
