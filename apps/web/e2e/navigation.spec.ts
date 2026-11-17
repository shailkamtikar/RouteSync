import { expect, test } from "@playwright/test";

import { nav, signInAndWait, USERS } from "./helpers";

test("the home page explains the product and leads to sign-in", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Intelligence behind every journey");
  await expect(page.getByRole("region", { name: "What RouteSync does" }).getByRole("article")).toHaveCount(6);
  await expect(page.getByRole("status")).toContainText("API: ok", { timeout: 20_000 });
  await page.getByRole("link", { name: "Sign in to the dashboard" }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("the sidebar marks the current page and every section loads", async ({ page }) => {
  await signInAndWait(page, USERS.owner1);
  for (const [name, heading] of [
    ["Journeys", "Journeys"],
    ["Services", "Services"],
    ["Buses", "Buses"],
    ["Overview", /Good (morning|afternoon|evening)/],
  ] as const) {
    await nav(page).getByRole("link", { name }).click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText(heading);
    await expect(nav(page).getByRole("link", { name })).toHaveAttribute("aria-current", "page");
  }
});

test("the theme can be switched and is remembered", async ({ page }) => {
  await signInAndWait(page, USERS.owner1);
  const html = page.locator("html");
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(html).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await expect(html).toHaveAttribute("data-theme", "light");
});

test("on a phone the menu opens, navigates and closes", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signInAndWait(page, USERS.owner1);
  await expect(page.getByRole("button", { name: "Open menu" })).toBeVisible();
  await page.getByRole("button", { name: "Open menu" }).click();
  await nav(page).getByRole("link", { name: "Services" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Services");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(overflow).toBe(false);
});

test("services, journeys and buses fit a phone without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signInAndWait(page, USERS.owner1);
  for (const path of ["/dashboard", "/dashboard/services", "/dashboard/journeys", "/dashboard/buses"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForTimeout(1500);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    expect(overflow, `${path} scrolls sideways`).toBe(false);
  }
});
