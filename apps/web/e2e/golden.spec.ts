import { expect, test } from "@playwright/test";

import { API, createDemoJourney, gpsPoint } from "./demo";
import { signInAndWait, USERS } from "./helpers";

/**
 * The whole product in one run: a second journey on the same route option stays isolated,
 * the operator records stops, the device reports, the passenger page follows, the assistant
 * answers, and the journey completes.
 */
test("golden journey from boarding to completion", async ({ page, request, context }) => {
  test.setTimeout(420_000);
  const a = createDemoJourney("boarding");
  const b = createDemoJourney("boarding"); // same route option, different bus and link
  const deviceA = { Authorization: `Bearer ${a.device_token}` };
  const deviceB = { Authorization: `Bearer ${b.device_token}` };

  // Each device token only moves its own journey.
  expect((await request.post(`${API}/api/v1/ingest/gps`, { headers: deviceA, data: { points: [gpsPoint(18.5204, 73.8567)] } })).status()).toBe(202);
  expect((await request.post(`${API}/api/v1/ingest/gps`, { headers: deviceB, data: { points: [gpsPoint(19.0948, 74.7496)] } })).status()).toBe(202);
  const viewA = await (await request.get(`${API}/api/v1/public/track/${a.tracking_url!.split("/track/")[1]}`)).json();
  const viewB = await (await request.get(`${API}/api/v1/public/track/${b.tracking_url!.split("/track/")[1]}`)).json();
  expect(viewA.bus.lat).toBeCloseTo(18.5204, 2);
  expect(viewB.bus.lat).toBeCloseTo(19.0948, 2);

  // Operator works journey A.
  const operator = await context.newPage();
  await signInAndWait(operator, USERS.owner1);
  await operator.goto(a.monitor_url);
  const events = operator.getByRole("table", { name: "Stop events" });
  const row = (name: string) => events.getByRole("row", { name: new RegExp(name) });
  await row("Pune").getByRole("button", { name: "Arrived" }).click();
  await row("Pune").getByLabel("Passenger count at Pune").fill("5");
  await row("Pune").getByRole("button", { name: "Boarded" }).click();
  await row("Pune").getByRole("button", { name: "Departed" }).click();
  await expect(operator.getByTestId("monitor-status")).toHaveText("in progress");

  // Passenger follows A and asks the assistant.
  await page.goto(a.tracking_url!);
  await expect(page.getByTestId("journey-status")).toContainText("On the way", { timeout: 25_000 });
  await expect(page.getByTestId("next-stop-card")).toContainText("Beed", { timeout: 25_000 });
  await page.getByTestId("companion").getByRole("button", { name: "How many stops are left?" }).click();
  await expect(page.getByTestId("companion-log")).toContainText(/Beed|2|two/, { timeout: 60_000 });

  // The bus reaches Beed, then Nanded; the journey completes.
  await request.post(`${API}/api/v1/ingest/gps`, { headers: deviceA, data: { points: [gpsPoint(18.9891, 75.7601)] } });
  await row("Beed").getByRole("button", { name: "Arrived" }).click();
  await row("Beed").getByLabel("Passenger count at Beed").fill("3");
  await row("Beed").getByRole("button", { name: "Alighted" }).click();
  await expect(operator.getByTestId("onboard-card").locator("strong")).toHaveText("2");
  await row("Beed").getByRole("button", { name: "Departed" }).click();
  await request.post(`${API}/api/v1/ingest/gps`, { headers: deviceA, data: { points: [gpsPoint(19.1383, 77.321)] } });
  await row("Nanded").getByRole("button", { name: "Arrived" }).click();
  await row("Nanded").getByRole("button", { name: "Finish journey" }).click();
  await expect(operator.getByTestId("monitor-status")).toHaveText("completed");

  await expect(page.getByTestId("journey-status")).toContainText("Journey completed", { timeout: 25_000 });
  await expect(page.getByTestId("finished-card")).toBeVisible();

  // Journey B is untouched by all of this.
  const afterB = await (await request.get(`${API}/api/v1/public/track/${b.tracking_url!.split("/track/")[1]}`)).json();
  expect(afterB.journey.status).toBe("boarding");
  expect(afterB.stops.every((s: { status: string }) => s.status !== "completed")).toBe(true);

  // A completed journey no longer accepts positions.
  expect((await request.post(`${API}/api/v1/ingest/gps`, { headers: deviceA, data: { points: [gpsPoint(19.14, 77.32)] } })).status()).toBe(409);
});
