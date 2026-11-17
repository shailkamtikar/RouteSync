import { expect, test } from "@playwright/test";

import { API, createDemoJourney, gpsPoint, onRoute } from "./demo";
import { signInAndWait, stopItem, USERS } from "./helpers";

test("operator monitors a running journey", async ({ page, request }) => {
  test.setTimeout(300_000);
  const demo = createDemoJourney("boarding");
  const device = { Authorization: `Bearer ${demo.device_token}` };

  await signInAndWait(page, USERS.owner2);
  await page.goto(`/dashboard/journeys/${demo.journey_id}/monitor`);
  await expect(page.getByTestId("monitor-status")).toContainText("Boarding");

  // Before any position: the ETA is plan-based and three cards are shown.
  await expect(page.getByTestId("next-stop-card")).toContainText("Pune");
  await expect(page.getByTestId("destination-card")).toContainText("Nanded");
  await expect(page.getByTestId("commitment-card")).toContainText("Promised at booking");
  await expect(page.getByTestId("onboard-card")).toContainText("planned");

  // Record what happens at the origin.
  const pune = stopItem(page, "Pune");
  await pune.getByRole("button", { name: "Arrived" }).click();
  await pune.getByLabel("Passenger count at Pune").fill("5");
  await pune.getByRole("button", { name: "Boarded" }).click();
  await expect(page.getByTestId("onboard-card")).toContainText("from recorded boardings");
  await expect(page.getByTestId("onboard-card").locator("strong")).toHaveText("5");
  await pune.getByRole("button", { name: "Departed" }).click();
  await expect(page.getByTestId("monitor-status")).toContainText("In progress");
  await expect(pune).toContainText("Departed");

  // A stop cannot be skipped: Nanded before Beed is refused.
  await stopItem(page, "Nanded").getByRole("button", { name: "Arrived" }).click();
  await expect(page.getByTestId("monitor-error")).toContainText("Beed");

  // The device reports a fresh position near Ahmednagar.
  const fresh = await request.post(`${API}/api/v1/ingest/gps`, {
    headers: device,
    data: { points: [onRoute(demo, 25)] },
  });
  expect(fresh.status()).toBe(202);
  expect((await fresh.json()).accepted).toBe(1);
  await expect(page.getByTestId("next-stop-card")).toContainText("Beed", { timeout: 20_000 });
  await expect(page.getByTestId("stale-banner")).toHaveCount(0);
  await expect(page.getByRole("img", { name: "Bus", exact: true })).toBeVisible();

  // Manual mode can be switched on.
  await page.getByLabel(/Manual mode/).click();
  await expect(page.getByLabel(/Manual mode/)).toBeChecked();

  // Incidents belong to the route option, which later runs reuse: start from none.
  const ended = page.getByRole("list", { name: "Active incidents" }).getByRole("button", { name: "End" });
  while ((await ended.count()) > 0) {
    await ended.first().click();
    await page.waitForTimeout(500);
  }

  // A simulated slowdown ahead is labelled as simulated.
  const incident = page.getByRole("form", { name: "Add simulated incident" });
  await incident.getByLabel("From km").fill("200");
  await incident.getByLabel("To km").fill("230");
  await incident.getByRole("button", { name: "Add incident" }).click();
  await expect(page.getByRole("list", { name: "Active incidents" })).toContainText("Simulated slowdown");
  await expect(page.getByTestId("monitor-alerts")).toContainText("Simulated slow traffic", { timeout: 20_000 });
  await ended.first().click();
  await expect(page.getByRole("list", { name: "Active incidents" })).toHaveCount(0);
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

  await signInAndWait(page, USERS.owner2);
  await page.goto(`/dashboard/journeys/${demo.journey_id}/monitor`);
  await expect(page.getByTestId("stale-banner")).toContainText("Location not live");
  await expect(page.getByRole("img", { name: "Bus (location not live)" })).toBeVisible();

  const otherContext = await browser.newContext();
  const otherPage = await otherContext.newPage();
  await signInAndWait(otherPage, USERS.owner1);
  await otherPage.goto(`/dashboard/journeys/${demo.journey_id}/monitor`);
  await expect(otherPage.getByRole("heading", { name: "Journey not found" })).toBeVisible();
  await otherContext.close();
});
