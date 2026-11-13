"""Create a complete demo journey through the public API, ready to be driven by the simulator.

It signs in as a seeded test operator and performs the same steps an operator would:
service -> route option -> stops -> bus -> journey -> bookings -> confirm stops -> assign route
-> publish -> start boarding -> create a device token.

Usage (API must be running on :8000):
    apps/api/.venv/Scripts/python scripts/demo_setup.py --out demo.json

The result (journey id, device token, public tracking link if available) is written as JSON to
--out, or to standard output when --out is not given. The file contains a secret token: keep it
out of version control (the default name demo.json is git-ignored).
"""

import argparse
import json
import secrets
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
api_env = dotenv_values(ROOT / "apps" / "api" / ".env")
web_env = dotenv_values(ROOT / "apps" / "web" / ".env.local")

PUNE = {"lat": 18.5204, "lng": 73.8567}
NANDED = {"lat": 19.1383, "lng": 77.321}
VIA = [
    {"name": "Ahmednagar", "lat": 19.0948, "lng": 74.7496},
    {"name": "Beed", "lat": 18.9891, "lng": 75.7601},
]
BOOKINGS = [(3, "Pune", "Beed"), (2, "Beed", "Nanded"), (2, "Pune", "Nanded")]


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.token = ""

    def call(
        self,
        method: str,
        path: str,
        body=None,
        *,
        absolute=False,
        headers=None,
        optional=False,
    ):
        url = path if absolute else f"{self.base}/api/v1{path}"
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
                **(headers or {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if optional and exc.code == 404:
                return None
            detail = exc.read().decode(errors="replace")[:300]
            sys.exit(f"{method} {path} failed: HTTP {exc.code} {detail}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--web", default="http://localhost:3000")
    parser.add_argument("--user", default="owner1@routesync.test")
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--status", default="boarding", choices=["ready", "published", "boarding"]
    )
    args = parser.parse_args()

    client = Client(args.api)
    session = client.call(
        "POST",
        f"{api_env['SUPABASE_URL'].rstrip('/')}/auth/v1/token?grant_type=password",
        {"email": args.user, "password": api_env["SEED_USER_PASSWORD"]},
        absolute=True,
        headers={"apikey": web_env["NEXT_PUBLIC_SUPABASE_ANON_KEY"]},
    )
    client.token = session["access_token"]

    service = client.call(
        "POST",
        "/services",
        {
            "origin_name": "Pune",
            "destination_name": "Nanded",
            "origin_location": PUNE,
            "destination_location": NANDED,
        },
    )
    created = client.call(
        "POST",
        f"/services/{service['id']}/route-templates",
        {"name": "Via Ahmednagar and Beed", "via_points": VIA},
    )
    if created["generation_error"]:
        sys.exit(f"route generation failed: {created['generation_error']}")
    template = created["template"]
    client.call(
        "POST",
        f"/route-templates/{template['id']}/stops",
        {"name": "Beed", "location": {"lat": VIA[1]["lat"], "lng": VIA[1]["lng"]}},
    )

    bus = client.call(
        "POST",
        "/buses",
        {"registration": f"MH12 {secrets.token_hex(3).upper()}", "capacity": 40},
    )
    now = datetime.now(UTC)
    journey = client.call(
        "POST",
        "/journeys",
        {
            "bus_id": bus["id"],
            "service_id": service["id"],
            "departure_at": now.isoformat(),
            "scheduled_arrival_at": (now + timedelta(hours=9)).isoformat(),
        },
    )
    jid = journey["id"]
    for count, pickup, drop in BOOKINGS:
        client.call(
            "POST",
            f"/journeys/{jid}/bookings",
            {
                "passenger_count": count,
                "pickup_stop_name": pickup,
                "drop_stop_name": drop,
            },
        )
    client.call(
        "PUT", f"/journeys/{jid}/route-template", {"route_template_id": template["id"]}
    )
    plan = client.call("GET", f"/journeys/{jid}/stop-plan")
    active = [
        {
            "route_template_stop_id": stop["route_template_stop_id"],
            "pickup_count": stop["booked_pickups"],
            "drop_count": stop["booked_drops"],
        }
        for stop in plan["stops"]
        if stop["booked_pickups"] + stop["booked_drops"] > 0
    ]
    client.call("PUT", f"/journeys/{jid}/active-stops", {"stops": active})
    client.call("POST", f"/journeys/{jid}/transition", {"to": "awaiting_confirmation"})
    client.call("POST", f"/journeys/{jid}/assign")

    result = {"journey_id": jid, "status": "ready", "route_template_id": template["id"]}
    if args.status in ("published", "boarding"):
        published = client.call(
            "POST", f"/journeys/{jid}/transition", {"to": "published"}
        )
        result["status"] = published["status"]
        link = client.call("POST", f"/journeys/{jid}/tracking-link", optional=True)
        if link:
            result["tracking_url"] = f"{args.web}/track/{link['token']}"
    if args.status == "boarding":
        result["status"] = client.call(
            "POST", f"/journeys/{jid}/transition", {"to": "boarding"}
        )["status"]
    result["device_token"] = client.call("POST", f"/journeys/{jid}/ingest-token")[
        "token"
    ]
    result["monitor_url"] = f"{args.web}/dashboard/journeys/{jid}/monitor"

    text = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(
            f"demo journey {jid} is {result['status']}; details written to {args.out}"
        )
    else:
        print(text)


if __name__ == "__main__":
    main()
