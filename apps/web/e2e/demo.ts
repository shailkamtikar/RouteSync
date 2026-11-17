import { execFileSync } from "node:child_process";
import path from "node:path";

export type Demo = {
  journey_id: string;
  status: string;
  device_token: string;
  tracking_url?: string;
  monitor_url: string;
  /** Points on the assigned road, by percentage of the way (5, 25, 55, 98). */
  route_positions: Record<string, { lat: number; lng: number }>;
};

const root = path.resolve(__dirname, "../../..");
const python =
  process.platform === "win32"
    ? path.join(root, "apps/api/.venv/Scripts/python.exe")
    : path.join(root, "apps/api/.venv/bin/python");

/**
 * Creates a fresh Pune to Nanded journey on its own bus, as the second seeded operator, so the
 * browser tests never touch the first operator's demo network. Returns its details.
 */
export function createDemoJourney(status: "ready" | "published" | "boarding" = "boarding"): Demo {
  const output = execFileSync(
    python,
    [
      path.join(root, "scripts/demo_setup.py"),
      "--new",
      "--user",
      "owner2@routesync.test",
      "--status",
      status,
    ],
    { encoding: "utf-8", timeout: 240_000 },
  );
  return JSON.parse(output) as Demo;
}

/** A device position on the demo journey's road, at this percentage of the way. */
export function onRoute(demo: Demo, percent: 5 | 25 | 55 | 98, secondsAgo = 0) {
  const point = demo.route_positions[String(percent)];
  return gpsPoint(point.lat, point.lng, secondsAgo);
}

export const API = "http://127.0.0.1:8010";

export function gpsPoint(lat: number, lng: number, secondsAgo = 0) {
  return {
    device_ts: new Date(Date.now() - secondsAgo * 1000).toISOString(),
    lat,
    lng,
    source: "e2e",
  };
}
