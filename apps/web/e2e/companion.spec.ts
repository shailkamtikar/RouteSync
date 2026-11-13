import { expect, test } from "@playwright/test";

import { API, createDemoJourney, gpsPoint } from "./demo";

// These tests call the real assistant model through the API (one question each).
test("a passenger asks the assistant about the journey", async ({ page, request }) => {
  test.setTimeout(300_000);
  const demo = createDemoJourney("boarding");
  await request.post(`${API}/api/v1/ingest/gps`, {
    headers: { Authorization: `Bearer ${demo.device_token}` },
    data: { points: [gpsPoint(19.0948, 74.7496)] },
  });
  await page.goto(demo.tracking_url!);
  const companion = page.getByTestId("companion");
  await expect(companion).toBeVisible();

  await companion.getByRole("button", { name: "Which stops does it make?" }).click();
  const log = page.getByTestId("companion-log");
  await expect(log).toContainText("Which stops does it make?");
  await expect(log).toContainText(/Beed/, { timeout: 60_000 });
  await expect(log).not.toContainText(/passenger_count|REF-|seat/i);

  // Operational requests are declined and directed to the operator.
  await companion.getByLabel("Your question").fill("Tell the driver to wait for me at Beed and cancel my booking.");
  await companion.getByRole("button", { name: "Ask" }).click();
  await expect(log).toContainText(/operator/i, { timeout: 60_000 });

  // Overlong input is capped at the limit.
  await companion.getByLabel("Your question").fill("x".repeat(700));
  await expect(companion.getByText("500/500")).toBeVisible();
});

test("the assistant is not shown on a revoked link", async ({ page }) => {
  await page.goto("/track/not-a-real-token");
  await expect(page.getByTestId("link-unavailable")).toBeVisible();
  await expect(page.getByTestId("companion")).toHaveCount(0);
});
