"""Prepare a journey for a live demo and write how to open it.

It reuses the network built by seed_network.py: it finds a journey of the chosen service in the
chosen state (or schedules a new one), then creates a public tracking link and a device token for it.
Nothing is created unless it is missing, so running it twice does not litter the database.

Usage (API on :8010, network seeded):
    apps/api/.venv/Scripts/python scripts/demo_setup.py --out demo.json

The result (journey id, monitor URL, public tracking URL, device token) is written as JSON to --out,
or to standard output. The file holds secret tokens: keep it out of version control (demo.json is
git-ignored).
"""

import argparse
import json
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_API, DEFAULT_WEB, signed_in


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--web", default=DEFAULT_WEB)
    parser.add_argument("--user", default="owner1@routesync.test")
    parser.add_argument("--origin", default="Pune")
    parser.add_argument("--destination", default="Nanded")
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--new",
        action="store_true",
        help="always schedule a fresh journey on its own new bus (used by the browser tests)",
    )
    parser.add_argument(
        "--status",
        default="boarding",
        choices=["ready", "published", "boarding", "in_progress"],
    )
    args = parser.parse_args()
    client = signed_in(args.api, args.user)

    journeys = (
        []
        if args.new
        else [
            j
            for j in client.call("GET", "/journeys")
            if (j["origin_name"], j["destination_name"])
            == (args.origin, args.destination)
            and j["status"] == args.status
        ]
    )
    if journeys:
        journey = max(journeys, key=lambda j: j["departure_at"])
    else:
        # Nothing suitable yet: schedule one on the existing service (building the network if needed).
        from seed_network import JOURNEYS, ensure_network, make_journey

        world = ensure_network(client, only=[(args.origin, args.destination)])
        bus = (
            client.call(
                "POST",
                "/buses",
                {
                    "registration": f"MH12 {secrets.token_hex(3).upper()}",
                    "capacity": 40,
                },
            )
            if args.new
            else None
        )
        spec = (args.origin, args.destination, 0, args.status, 10, 0)
        if not args.new:
            spec = next(
                (s for s in JOURNEYS if (s[0], s[1], s[3]) == spec[:2] + spec[3:4]),
                spec,
            )
        bookings = None
        if args.new:
            # Fixed, easy-to-assert bookings: the middle stop of the route is the one that matters.
            option = world["network"][(args.origin, args.destination)]["corridor"][
                "options"
            ][0]
            middle = option["stops"][len(option["stops"]) // 2]
            bookings = [
                (3, args.origin, middle),
                (2, middle, args.destination),
                (2, args.origin, args.destination),
            ]
        jid = make_journey(client, world, spec, datetime.now(UTC), bus, bookings)
        journey = client.call("GET", f"/journeys/{jid}")

    jid = journey["id"]
    result = {"journey_id": jid, "status": journey["status"]}
    if journey["status"] in ("published", "boarding", "in_progress"):
        link = client.call("POST", f"/journeys/{jid}/tracking-link", optional=True)
        if link:
            result["tracking_url"] = f"{args.web}/track/{link['token']}"
    result["device_token"] = client.call("POST", f"/journeys/{jid}/ingest-token")[
        "token"
    ]
    # Points that lie on the assigned road, for driving a device by hand (tests, demos).
    from fleet_simulator import Line

    route = client.call("GET", f"/journeys/{jid}/monitor")["route"]
    if route:
        line = Line([tuple(c) for c in route["coordinates"]])
        result["route_positions"] = {
            str(pct): dict(
                zip(("lng", "lat"), line.at(line.length * pct / 100), strict=True)
            )
            for pct in (5, 25, 55, 98)
        }
    result["monitor_url"] = f"{args.web}/dashboard/journeys/{jid}/monitor"
    result["journey_url"] = f"{args.web}/dashboard/journeys/{jid}"

    text = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"journey {jid} ({result['status']}); details written to {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
