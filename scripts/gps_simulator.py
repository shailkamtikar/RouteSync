"""Drive a simulated bus along a journey's assigned route.

The simulator is an ordinary device: it only knows the journey's device token and talks to
the same ingestion endpoint a real GPS unit would use.

Usage:
    python scripts/gps_simulator.py --token <device token> --speed 20

Options:
    --api URL             API base URL (default http://127.0.0.1:8000)
    --speed N             time multiplier: 20 means the trip runs 20 times faster (default 20)
    --interval S          seconds between position reports (default 2)
    --start F             start at this fraction of the route, 0..1 (default 0)
    --stop-at F           stop at this fraction of the route (default 1)
    --dropout-at F        go silent when this fraction is reached ...
    --dropout-seconds S   ... for this many seconds, then send the missed points as one batch
    --duplicates          send every report twice (tests idempotency)
    --jitter-m M          random GPS noise in metres (default 10)
The token can also be given in the GPS_INGEST_TOKEN environment variable.
"""

import argparse
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

EARTH_M = 6_371_008.8


def haversine_m(a, b) -> float:
    lng1, lat1, lng2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * EARTH_M * math.asin(math.sqrt(h))


class Route:
    def __init__(self, coordinates):
        self.coordinates = coordinates
        self.cumulative = [0.0]
        for previous, current in zip(coordinates, coordinates[1:], strict=False):
            self.cumulative.append(self.cumulative[-1] + haversine_m(previous, current))
        self.length = self.cumulative[-1]

    def at(self, fraction: float):
        """Point (lng, lat) at a fraction of the route's length."""
        target = max(0.0, min(1.0, fraction)) * self.length
        for index in range(1, len(self.cumulative)):
            if self.cumulative[index] >= target:
                span = self.cumulative[index] - self.cumulative[index - 1] or 1.0
                t = (target - self.cumulative[index - 1]) / span
                a, b = self.coordinates[index - 1], self.coordinates[index]
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        return tuple(self.coordinates[-1])


def call(method: str, url: str, token: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except ValueError:
            return exc.code, {}
    except (urllib.error.URLError, TimeoutError) as exc:
        return None, {"detail": str(exc)}


def jitter(point, metres: float):
    if metres <= 0:
        return point
    dlat = random.uniform(-metres, metres) / 111_320
    dlng = random.uniform(-metres, metres) / (
        111_320 * math.cos(math.radians(point[1])) or 1
    )
    return (point[0] + dlng, point[1] + dlat)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simulated bus GPS for one RouteSync journey"
    )
    parser.add_argument("--token", default=os.environ.get("GPS_INGEST_TOKEN", ""))
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--speed", type=float, default=20.0)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--stop-at", type=float, default=1.0)
    parser.add_argument("--dropout-at", type=float, default=None)
    parser.add_argument("--dropout-seconds", type=float, default=30.0)
    parser.add_argument("--duplicates", action="store_true")
    parser.add_argument("--jitter-m", type=float, default=10.0)
    args = parser.parse_args()
    if not args.token:
        parser.error("a device token is required (--token or GPS_INGEST_TOKEN)")

    status, body = call("GET", f"{args.api}/api/v1/ingest/route", args.token)
    if status != 200:
        print(f"could not load the route: HTTP {status} {body.get('detail', '')}")
        return 1
    route = Route(body["coordinates"])
    duration_s = float(body["duration_s"] or route.length / 16.7)
    print(
        f"route: {route.length / 1000:.0f} km, drive time {duration_s / 3600:.1f} h, x{args.speed:g}"
    )

    fraction = args.start
    step = args.interval * args.speed / duration_s
    backlog: list[dict] = []
    silent_until = 0.0
    dropout_done = args.dropout_at is None
    while True:
        lng, lat = jitter(route.at(fraction), args.jitter_m)
        report = {
            "device_ts": datetime.now(UTC).isoformat(),
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "speed_mps": round(route.length / duration_s, 1),
            "accuracy_m": args.jitter_m,
            "source": "simulator",
        }
        if not dropout_done and fraction >= args.dropout_at:
            dropout_done = True
            silent_until = time.monotonic() + args.dropout_seconds
            print(f"  simulated signal loss for {args.dropout_seconds:g} s")
        backlog.append(report)
        if time.monotonic() >= silent_until:
            batch, backlog = backlog[-50:], []
            sends = 2 if args.duplicates else 1
            for _ in range(sends):
                status, result = call(
                    "POST",
                    f"{args.api}/api/v1/ingest/gps",
                    args.token,
                    {"points": batch},
                )
            if status == 202:
                note = (
                    f"accepted {result['accepted']}, duplicates {result['duplicates']}"
                )
                if result["rejected"]:
                    note += f", rejected {result['rejected']}"
            elif status == 409:
                print("  the journey is no longer accepting positions; stopping")
                return 0
            elif status == 401:
                print("  the device token was rejected; stopping")
                return 1
            else:
                note = f"HTTP {status} {result.get('detail', '')} (will retry)"
                backlog = batch
            print(f"  {fraction * 100:5.1f}%  {lat:.4f},{lng:.4f}  {note}")
        if fraction >= args.stop_at:
            print("reached the end of the simulated run")
            return 0
        fraction = min(args.stop_at, fraction + step)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
