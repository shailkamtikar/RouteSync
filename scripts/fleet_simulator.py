"""Keep every in-progress bus of an operator moving along its route, like a fleet of GPS devices.

Each bus is an ordinary device: it asks for its own device token and posts positions to the same
ingestion endpoint a real unit would use. When a bus passes a stop, the matching stop events
(arrived, then departed) are recorded as an operator would; the journey completes at the destination.

Usage (API on :8010, journeys seeded by seed_network.py):
    apps/api/.venv/Scripts/python scripts/fleet_simulator.py --speedup 30

Stop with Ctrl+C. --speedup multiplies real speed (default 25) so movement is visible on screen.
"""

import argparse
import itertools
import json
import math
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import Client, signed_in


def haversine_m(a, b) -> float:
    rad = math.pi / 180
    d_lat = (b[1] - a[1]) * rad
    d_lng = (b[0] - a[0]) * rad
    h = (
        math.sin(d_lat / 2) ** 2
        + math.cos(a[1] * rad) * math.cos(b[1] * rad) * math.sin(d_lng / 2) ** 2
    )
    return 12_742_000 * math.asin(math.sqrt(h))


class Line:
    def __init__(self, coordinates):
        self.points = coordinates
        self.cumulative = [0.0]
        for a, b in itertools.pairwise(coordinates):
            self.cumulative.append(self.cumulative[-1] + haversine_m(a, b))
        self.length = self.cumulative[-1]

    def at(self, distance: float):
        distance = max(0.0, min(self.length, distance))
        lo, hi = 0, len(self.cumulative) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if self.cumulative[mid] <= distance:
                lo = mid
            else:
                hi = mid
        span = self.cumulative[hi] - self.cumulative[lo] or 1.0
        t = (distance - self.cumulative[lo]) / span
        a, b = self.points[lo], self.points[hi]
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    def chainage_of(self, point) -> float:
        best, best_distance = 0.0, float("inf")
        for index, vertex in enumerate(self.points):
            gap = haversine_m(vertex, point)
            if gap < best_distance:
                best, best_distance = self.cumulative[index], gap
        return best


class Bus:
    def __init__(self, client: Client, journey: dict):
        self.client = client
        self.id = journey["id"]
        self.label = f"{journey['origin_name']} -> {journey['destination_name']}"
        monitor = client.call("GET", f"/journeys/{self.id}/monitor")
        self.line = Line([tuple(c) for c in monitor["route"]["coordinates"]])
        self.stops = [
            {
                "id": s["journey_stop_id"],
                "name": s["name"],
                "status": s["status"],
                "at": self.line.chainage_of((s["lng"], s["lat"])),
                "role": s["role"],
            }
            for s in monitor["stops"]
        ]
        start = datetime.fromisoformat(journey["departure_at"])
        end = datetime.fromisoformat(journey["scheduled_arrival_at"])
        fraction = (datetime.now(UTC) - start) / (end - start)
        position = monitor["position"]
        self.distance = (
            self.line.chainage_of((position["lng"], position["lat"]))
            if position
            else self.line.length * min(0.9, max(0.05, fraction))
        )
        self.token = client.call("POST", f"/journeys/{self.id}/ingest-token")["token"]
        self.speed_mps = 70 / 3.6
        self.done = False

    def post(self, path: str, body: dict, token: str | None = None):
        request = urllib.request.Request(
            f"{self.client.base}/api/v1{path}",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token or self.client.token}",
            },
        )
        try:
            return json.loads(
                urllib.request.urlopen(request, timeout=60).read() or "null"
            )
        except urllib.error.HTTPError as exc:
            print(f"  {self.label}: {path} -> {exc.code} {exc.read().decode()[:100]}")
            return None

    def stop_event(self, stop: dict, kind: str) -> None:
        self.post(
            f"/journeys/{self.id}/stop-events",
            {
                "journey_stop_id": stop["id"],
                "type": kind,
                "count": 0,
                "client_event_id": str(uuid.uuid4()),
            },
        )

    def tick(self, seconds: float, speedup: float) -> None:
        if self.done:
            return
        self.distance = min(
            self.line.length, self.distance + self.speed_mps * speedup * seconds
        )
        lng, lat = self.line.at(self.distance)
        self.post(
            "/ingest/gps",
            {
                "points": [
                    {
                        "device_ts": datetime.now(UTC).isoformat(),
                        "lat": lat,
                        "lng": lng,
                        "speed_mps": self.speed_mps,
                    }
                ]
            },
            token=self.token,
        )
        for stop in self.stops:
            if stop["status"] == "departed" or stop["at"] > self.distance + 150:
                continue
            if stop["status"] == "pending":
                self.stop_event(stop, "arrived")
                stop["status"] = "arrived"
            if stop["status"] == "arrived":
                self.stop_event(stop, "departed")
                stop["status"] = "departed"
                print(f"  {self.label}: passed {stop['name']}")
        if self.distance >= self.line.length - 1:
            self.done = True
            print(f"  {self.label}: arrived")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8010")
    parser.add_argument("--user", default="owner1@routesync.test")
    parser.add_argument("--speedup", type=float, default=25.0)
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args()

    client = signed_in(args.api, args.user)
    started = time.time()
    fleet = [
        Bus(client, j)
        for j in client.call("GET", "/journeys")
        if j["status"] == "in_progress" and j["route_template_id"]
    ]
    if not fleet:
        sys.exit("No journey is in progress. Run scripts/seed_network.py first.")
    print(f"moving {len(fleet)} buses at {args.speedup:g}x; press Ctrl+C to stop")
    try:
        while any(not bus.done for bus in fleet):
            for bus in fleet:
                bus.tick(args.interval, args.speedup)
            # The sign-in token lasts an hour; renew it well before that.
            if time.time() - started > 2400:
                client.refresh()
                started = time.time()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
