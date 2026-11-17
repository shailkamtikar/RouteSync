"""Build a realistic Maharashtra operating network through the public API.

Creates a fleet, one service per corridor in apps/web/src/data/corridors.json (each with its
named route options and confirmed stops) and journeys in every lifecycle state, with bookings
and, for journeys under way, a simulated bus position. Everything goes through the same endpoints
an operator uses, so it exercises the real validation.

Usage (API on :8010, dev database; run reset_dev_data.py first for a clean start):
    apps/api/.venv/Scripts/python scripts/seed_network.py
"""

import argparse
import json
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import Client, signed_in

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "apps" / "web" / "src" / "data"
PLACES = {
    p["name"]: p for p in json.loads((DATA / "places.json").read_text(encoding="utf-8"))
}
CORRIDORS = json.loads((DATA / "corridors.json").read_text(encoding="utf-8"))

BUSES = [
    ("MH12 QR 4101", 45),
    ("MH12 QR 4102", 45),
    ("MH12 QR 4103", 40),
    ("MH01 AX 2201", 50),
    ("MH01 AX 2202", 50),
    ("MH31 CB 7301", 40),
    ("MH31 CB 7302", 36),
    ("MH15 DT 5501", 45),
    ("MH20 EM 6601", 40),
    ("MH20 EM 6602", 32),
    ("MH09 FK 3301", 45),
    ("MH13 GS 8801", 40),
    ("MH26 HN 9901", 36),
    ("MH24 JL 1101", 40),
    ("MH12 QR 4104", 50),
    ("MH04 TH 1201", 45),
    ("MH12 QR 4105", 45),
    ("MH01 AX 2203", 40),
    ("MH31 CB 7303", 45),
    ("MH15 DT 5502", 36),
]

# (from, to, option, state, departure offset in minutes from now, bus index)
JOURNEYS = [
    ("Mumbai", "Pune", 0, "completed", -26 * 60, 0),
    ("Pune", "Kolhapur", 0, "completed", -20 * 60, 1),
    ("Nagpur", "Chhatrapati Sambhajinagar", 0, "completed", -34 * 60, 2),
    ("Pune", "Nashik", 1, "completed", -14 * 60, 3),
    ("Pune", "Nanded", 0, "in_progress", -190, 4),
    ("Mumbai", "Nagpur", 0, "in_progress", -300, 5),
    ("Nashik", "Chhatrapati Sambhajinagar", 0, "in_progress", -95, 6),
    ("Pune", "Solapur", 1, "in_progress", -70, 7),
    ("Pune", "Nanded", 1, "boarding", 12, 8),
    ("Mumbai", "Pune", 1, "boarding", 25, 9),
    ("Mumbai", "Nashik", 0, "published", 180, 10),
    ("Pune", "Latur", 1, "published", 300, 11),
    ("Nanded", "Nagpur", 0, "published", 480, 12),
    ("Pune", "Shirdi", 0, "published", 14 * 60, 13),
    ("Mumbai", "Kolhapur", 1, "published", 20 * 60, 14),
    ("Pune", "Chhatrapati Sambhajinagar", 0, "ready", 30 * 60, 15),
    ("Nashik", "Nagpur", 0, "ready", 36 * 60, 16),
    ("Chhatrapati Sambhajinagar", "Nanded", 0, "awaiting_confirmation", 48 * 60, 17),
    ("Pune", "Nanded", 2, "draft", 60 * 60, 18),
    ("Mumbai", "Nagpur", 1, "draft", 72 * 60, 19),
]
rng = random.Random(7)


def point(name: str) -> dict:
    place = PLACES[name]
    return {"lat": place["lat"], "lng": place["lng"]}


def generate(client: Client, template_id: str):
    for attempt in range(4):
        result = client.call("POST", f"/route-templates/{template_id}/generate")
        error = result.get("generation_error") if isinstance(result, dict) else None
        if not error:
            return result
        print(
            f"    routing said: {error}; retrying in {20 * (attempt + 1)} s",
            file=sys.stderr,
        )
        time.sleep(20 * (attempt + 1))
    sys.exit("route generation kept failing")


def ensure_network(client: Client, only: list[tuple[str, str]] | None = None) -> dict:
    """Create what is missing: the fleet and every corridor (or just the pairs in `only`)."""
    buses = {b["registration"]: b for b in client.call("GET", "/buses")}
    if only is None:
        for registration, capacity in BUSES:
            if registration not in buses:
                buses[registration] = client.call(
                    "POST",
                    "/buses",
                    {"registration": registration, "capacity": capacity},
                )
    services = {
        (s["origin_name"], s["destination_name"]): s
        for s in client.call("GET", "/services")
    }
    network = {}
    for corridor in CORRIDORS:
        key = (corridor["from"], corridor["to"])
        if only is not None and key not in only:
            continue
        service = services.get(key) or client.call(
            "POST",
            "/services",
            {
                "origin_name": key[0],
                "destination_name": key[1],
                "origin_location": point(key[0]),
                "destination_location": point(key[1]),
            },
        )
        existing = {
            t["name"]: t
            for t in client.call("GET", f"/services/{service['id']}/route-templates")
        }
        templates = []
        for option in corridor["options"]:
            template = existing.get(option["name"])
            if template is not None and template.get("status") != "ready":
                template = generate(client, template["id"])["template"]
                print(f"  repaired route option {option['name']}", file=sys.stderr)
            if template is None:
                created = client.call(
                    "POST",
                    f"/services/{service['id']}/route-templates",
                    {
                        "name": option["name"],
                        "via_points": [{"name": v, **point(v)} for v in option["via"]],
                    },
                )
                template = created["template"]
                if created["generation_error"]:
                    template = generate(client, template["id"])["template"]
                for stop in option["stops"]:
                    client.call(
                        "POST",
                        f"/route-templates/{template['id']}/stops",
                        {"name": stop, "location": point(stop)},
                    )
                time.sleep(1.8)
                km = (template.get("distance_m") or 0) / 1000
                print(
                    f"  {key[0]} -> {key[1]}: {option['name']} ({km:.0f} km)",
                    file=sys.stderr,
                )
            templates.append(template)
        network[key] = {
            "service": service,
            "templates": templates,
            "corridor": corridor,
        }
    return {"buses": buses, "network": network}


def make_journey(
    client: Client,
    world: dict,
    spec,
    now: datetime,
    bus: dict | None = None,
    bookings: list[tuple[int, str, str]] | None = None,
) -> str | None:
    """Create one journey in the state `spec` names; `bookings` fixes them (count, pickup, drop)."""
    origin, destination, option, state, offset, bus_index = spec
    entry = world["network"][(origin, destination)]
    template = entry["templates"][option]
    if bus is None:
        bus = world["buses"][BUSES[bus_index][0]]
    capacity = bus["capacity"]
    departure = now + timedelta(minutes=offset)
    hours = max(1.0, (template.get("duration_s") or 3 * 3600) * 1.12 / 3600)
    journey = client.call(
        "POST",
        "/journeys",
        {
            "bus_id": bus["id"],
            "service_id": entry["service"]["id"],
            "departure_at": departure.isoformat(),
            "scheduled_arrival_at": (departure + timedelta(hours=hours)).isoformat(),
        },
    )
    jid = journey["id"]
    names = [origin, *entry["corridor"]["options"][option]["stops"], destination]
    planned = bookings
    if planned is None:
        planned = []
        passengers = 0
        for _ in range(rng.randint(5, 9)):
            a = rng.randrange(0, len(names) - 1)
            b = rng.randrange(a + 1, len(names))
            count = rng.randint(1, 4)
            if passengers + count > capacity - 4:
                continue
            passengers += count
            planned.append((count, names[a], names[b]))
    for count, pickup, drop in planned:
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
    if state == "draft":
        return jid
    plan = client.call("GET", f"/journeys/{jid}/stop-plan")
    active = [
        {
            "route_template_stop_id": s["route_template_stop_id"],
            "pickup_count": s["booked_pickups"],
            "drop_count": s["booked_drops"],
        }
        for s in plan["stops"]
        if s["booked_pickups"] + s["booked_drops"] > 0
    ]
    client.call("PUT", f"/journeys/{jid}/active-stops", {"stops": active})
    client.call("POST", f"/journeys/{jid}/transition", {"to": "awaiting_confirmation"})
    if state == "awaiting_confirmation":
        return jid
    client.call("POST", f"/journeys/{jid}/assign")
    if state == "ready":
        return jid
    client.call("POST", f"/journeys/{jid}/transition", {"to": "published"})
    client.call("POST", f"/journeys/{jid}/tracking-link", optional=True)
    if state == "published":
        return jid
    client.call("POST", f"/journeys/{jid}/transition", {"to": "boarding"})
    if state == "boarding":
        return jid
    client.call("POST", f"/journeys/{jid}/transition", {"to": "in_progress"})
    if state == "in_progress":
        place_bus(client, jid)
        return jid
    client.call("POST", f"/journeys/{jid}/transition", {"to": "completed"})
    return jid


def place_bus(client: Client, jid: str) -> None:
    """Put a bus under way where its schedule says it is, and record the stops it has passed."""
    from fleet_simulator import Bus

    journey = client.call("GET", f"/journeys/{jid}")
    Bus(client, journey).tick(0, 1)


def place_all(client: Client) -> None:
    """Position every journey that is under way (safe to run again)."""
    for journey in client.call("GET", "/journeys"):
        if journey["status"] != "in_progress" or not journey["route_template_id"]:
            continue
        place_bus(client, journey["id"])
        print(f"  placed {journey['origin_name']} -> {journey['destination_name']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--place-buses", action="store_true", help="only position buses under way"
    )
    parser.add_argument("--api", default="http://127.0.0.1:8010")
    parser.add_argument("--user", default="owner1@routesync.test")
    parser.add_argument(
        "--force", action="store_true", help="add journeys even if some exist"
    )
    args = parser.parse_args()
    client = signed_in(args.api, args.user)
    if args.place_buses:
        place_all(client)
        return
    print("building services and route options")
    world = ensure_network(client)
    if client.call("GET", "/journeys") and not args.force:
        print("journeys already exist; use --force to add more")
        return
    now = datetime.now(UTC)
    print("creating journeys")
    for spec in JOURNEYS:
        try:
            make_journey(client, world, spec, now)
            print(f"  {spec[0]} -> {spec[1]} option {spec[2] + 1}: {spec[3]}")
        except SystemExit as exc:
            print(f"  FAILED {spec[0]} -> {spec[1]} ({spec[3]}): {exc}")
        time.sleep(1.5)


if __name__ == "__main__":
    main()
