import { execFileSync } from "node:child_process";
import path from "node:path";

export type Demo = {
  journey_id: string;
  status: string;
  route_template_id: string;
  device_token: string;
  tracking_url?: string;
  monitor_url: string;
};

const root = path.resolve(__dirname, "../../..");
const python =
  process.platform === "win32"
    ? path.join(root, "apps/api/.venv/Scripts/python.exe")
    : path.join(root, "apps/api/.venv/bin/python");

/** Creates a demo journey through the API (as the seeded owner) and returns its details. */
export function createDemoJourney(status: "ready" | "published" | "boarding" = "boarding"): Demo {
  const output = execFileSync(
    python,
    [path.join(root, "scripts/demo_setup.py"), "--status", status],
    { encoding: "utf-8", timeout: 180_000 },
  );
  return JSON.parse(output) as Demo;
}

export const API = "http://127.0.0.1:8000";

export function gpsPoint(lat: number, lng: number, secondsAgo = 0) {
  return {
    device_ts: new Date(Date.now() - secondsAgo * 1000).toISOString(),
    lat,
    lng,
    source: "e2e",
  };
}
