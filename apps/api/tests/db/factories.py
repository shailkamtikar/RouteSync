"""Row factories for database tests. Everything is rolled back by the `conn` fixture."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import psycopg

LINE = "LINESTRING(73.8567 18.5204, 75.7600 18.9900, 77.3210 19.1383)"
T0 = datetime(2030, 1, 1, 6, 0, tzinfo=UTC)

JOURNEY_TABLES = [
    "bookings",
    "booking_passengers",
    "journey_stops",
    "journey_stop_passengers",
    "route_versions",
    "gps_positions",
    "stop_events",
    "journey_eta_snapshots",
    "journey_alerts",
    "journey_events",
]
OPERATOR_TABLES = ["buses", "services", "route_templates", "route_template_stops", "journeys"]
MEMBER_READABLE_TABLES = OPERATOR_TABLES + JOURNEY_TABLES
ALL_DOMAIN_TABLES = MEMBER_READABLE_TABLES + ["public_tracking_links"]


def one(c: psycopg.Connection, sql: str, params=()):
    return c.execute(sql, params).fetchone()[0]


def make_bus(c, op, registration=None, capacity=40):
    return one(
        c,
        "insert into public.buses (operator_id, registration, capacity) "
        "values (%s, %s, %s) returning id",
        (op, registration or f"MH12{uuid.uuid4().hex[:6].upper()}", capacity),
    )


def make_service(c, op, origin="Pune", destination="Nanded"):
    return one(
        c,
        "insert into public.services (operator_id, origin_name, destination_name) "
        "values (%s, %s, %s) returning id",
        (op, origin, destination),
    )


def make_template(c, op, service, name="North corridor"):
    return one(
        c,
        "insert into public.route_templates (operator_id, service_id, name, geometry, status) "
        "values (%s, %s, %s, %s::extensions.geography, 'ready') returning id",
        (op, service, name, LINE),
    )


def make_template_stop(c, op, template, name, lng=75.76, lat=18.99, kind="passenger_stop"):
    return one(
        c,
        "insert into public.route_template_stops "
        "(operator_id, route_template_id, name, location, kind) "
        "values (%s, %s, %s, %s::extensions.geography, %s) returning id",
        (op, template, name, f"POINT({lng} {lat})", kind),
    )


def make_journey(c, op, bus, service, template=None, start=T0, hours=9, status="draft"):
    end = start + timedelta(hours=hours)
    return one(
        c,
        "insert into public.journeys (operator_id, bus_id, service_id, route_template_id, "
        "departure_at, scheduled_arrival_at, booking_eta_at, status) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
        (op, bus, service, template, start, end, end, status),
    )


def make_booking(c, op, journey, reference=None, count=2):
    return one(
        c,
        "insert into public.bookings (operator_id, journey_id, reference, passenger_count, "
        "pickup_stop_name, drop_stop_name) values (%s, %s, %s, %s, 'Pune', 'Nanded') returning id",
        (op, journey, reference or uuid.uuid4().hex[:10], count),
    )


def make_passenger(c, op, journey, booking, name="Asha Kulkarni", seat="12A"):
    return one(
        c,
        "insert into public.booking_passengers (operator_id, journey_id, booking_id, name, "
        "seat_number, phone) values (%s, %s, %s, %s, %s, '+919800000000') returning id",
        (op, journey, booking, name, seat),
    )


def make_journey_stop(c, op, journey, template, template_stop, sequence=1):
    return one(
        c,
        "insert into public.journey_stops (operator_id, journey_id, route_template_id, "
        "route_template_stop_id, sequence, pickup_count) values (%s, %s, %s, %s, %s, 2) "
        "returning id",
        (op, journey, template, template_stop, sequence),
    )


def make_route_version(c, op, journey, version=1):
    return one(
        c,
        "insert into public.route_versions (operator_id, journey_id, version, geometry, reason, "
        "source) values (%s, %s, %s, %s::extensions.geography, 'initial plan', "
        "'operator_initial') returning id",
        (op, journey, version, LINE),
    )


def make_gps(c, op, journey, device_ts=T0, source="simulator"):
    return one(
        c,
        "insert into public.gps_positions (operator_id, journey_id, location, device_ts, source) "
        "values (%s, %s, 'POINT(73.9 18.6)'::extensions.geography, %s, %s) returning id",
        (op, journey, device_ts, source),
    )


def make_stop_event(c, op, journey, journey_stop, event_type="arrived", client_event_id=None):
    return one(
        c,
        "insert into public.stop_events (operator_id, journey_id, journey_stop_id, type, "
        "client_event_id, occurred_at) values (%s, %s, %s, %s, %s, %s) returning id",
        (op, journey, journey_stop, event_type, client_event_id or uuid.uuid4().hex, T0),
    )


def make_event(c, op, journey, event_type="journey_created"):
    return one(
        c,
        "insert into public.journey_events (operator_id, journey_id, event_type) "
        "values (%s, %s, %s) returning id",
        (op, journey, event_type),
    )


def make_world(c: psycopg.Connection, op) -> dict:
    """Create one row in every domain table for the given operator."""
    w = {"op": op}
    w["bus"] = make_bus(c, op)
    w["service"] = make_service(c, op)
    w["template"] = make_template(c, op, w["service"])
    w["stop_a"] = make_template_stop(c, op, w["template"], "Ahmednagar", 74.74, 19.09)
    w["stop_b"] = make_template_stop(c, op, w["template"], "Beed", 75.76, 18.99)
    w["journey"] = make_journey(c, op, w["bus"], w["service"], w["template"])
    w["booking"] = make_booking(c, op, w["journey"])
    w["passenger"] = make_passenger(c, op, w["journey"], w["booking"])
    w["journey_stop"] = make_journey_stop(c, op, w["journey"], w["template"], w["stop_a"])
    c.execute(
        "insert into public.journey_stop_passengers (operator_id, journey_id, journey_stop_id, "
        "booking_passenger_id, action) values (%s, %s, %s, %s, 'pickup')",
        (op, w["journey"], w["journey_stop"], w["passenger"]),
    )
    w["route_version"] = make_route_version(c, op, w["journey"])
    make_gps(c, op, w["journey"])
    make_stop_event(c, op, w["journey"], w["journey_stop"])
    c.execute(
        "insert into public.journey_eta_snapshots (operator_id, journey_id, route_version_id, "
        "payload) values (%s, %s, %s, '{}')",
        (op, w["journey"], w["route_version"]),
    )
    c.execute(
        "insert into public.journey_alerts (operator_id, journey_id, type, severity, message) "
        "values (%s, %s, 'delay', 'warning', 'Running late')",
        (op, w["journey"]),
    )
    c.execute(
        "insert into public.public_tracking_links (operator_id, journey_id, token_hash) "
        "values (%s, %s, %s)",
        (op, w["journey"], hashlib.sha256(uuid.uuid4().bytes).hexdigest()),
    )
    make_event(c, op, w["journey"])
    return w
