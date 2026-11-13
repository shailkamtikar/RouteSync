"""A running journey on a realistic northern Pune-Nanded route, for live-journey tests."""

from datetime import UTC, datetime, timedelta

from psycopg.types.json import Jsonb

from app.auth.deps import OperatorContext
from app.providers.routing.fake import FakeRoutingProvider

from . import factories as f

PUNE = (73.8567, 18.5204)
AHMEDNAGAR = (74.7496, 19.0948)
BEED = (75.7601, 18.9891)
PARBHANI = (76.7748, 19.2608)
NANDED = (77.321, 19.1383)
ROUTE = FakeRoutingProvider().route([PUNE, AHMEDNAGAR, BEED, PARBHANI, NANDED])[0]


def wkt(coordinates) -> str:
    return "LINESTRING(" + ", ".join(f"{lng} {lat}" for lng, lat in coordinates) + ")"


def build_live_journey(
    conn,
    tenants,
    *,
    operator="op1",
    owner="owner1",
    status="in_progress",
    position=AHMEDNAGAR,
    promise_in_hours=12.0,
    bus=None,
    template=None,
    service=None,
):
    """Template with real geometry, active stops Beed and Parbhani, an assigned route version
    and a fresh position. Returns ids and an operator context."""
    op = tenants[operator]
    now = datetime.now(UTC)
    service = service or f.make_service(conn, op)
    if template is None:
        template = conn.execute(
            "insert into public.route_templates (operator_id, service_id, name, geometry, "
            "distance_m, duration_s, provider, provider_metadata, status) values (%s, %s, %s, "
            "%s::extensions.geography, %s, %s, 'fake', %s, 'ready') returning id",
            (
                op,
                service,
                f"North {now.timestamp()}",
                wkt(ROUTE.coordinates),
                ROUTE.distance_m,
                ROUTE.duration_s,
                Jsonb({"corridor_width_m": 5000}),
            ),
        ).fetchone()[0]
        for name, point, role in (
            ("Pune", PUNE, "origin"),
            ("Beed", BEED, "intermediate"),
            ("Parbhani", PARBHANI, "intermediate"),
            ("Nanded", NANDED, "destination"),
        ):
            stop = f.make_template_stop(conn, op, template, name, *point)
            conn.execute(
                "update public.route_template_stops set role = %s, chainage_m = "
                "extensions.st_linelocatepoint(%s::extensions.geometry, location::extensions.geometry) * %s "
                "where id = %s",
                (role, f"SRID=4326;{wkt(ROUTE.coordinates)}", ROUTE.distance_m, stop),
            )
    stops = dict(
        conn.execute(
            "select name, id from public.route_template_stops where route_template_id = %s",
            (template,),
        ).fetchall()
    )
    bus = bus or f.make_bus(conn, op)
    journey = f.make_journey(
        conn,
        op,
        bus,
        service,
        template,
        start=now - timedelta(hours=1),
        hours=1 + promise_in_hours,
        status=status,
    )
    journey_stops = {}
    for sequence, name in enumerate(("Beed", "Parbhani"), start=1):
        journey_stops[name] = conn.execute(
            "insert into public.journey_stops (operator_id, journey_id, route_template_id, "
            "route_template_stop_id, sequence, pickup_count, drop_count) "
            "values (%s, %s, %s, %s, %s, 2, 1) returning id",
            (op, journey, template, stops[name], sequence),
        ).fetchone()[0]
    version = conn.execute(
        "insert into public.route_versions (operator_id, journey_id, version, geometry, "
        "distance_m, duration_s, reason, source) values (%s, %s, 1, %s::extensions.geography, "
        "%s, %s, 'Route assigned by operator', 'operator_initial') returning id",
        (op, journey, wkt(ROUTE.coordinates), ROUTE.distance_m, ROUTE.duration_s),
    ).fetchone()[0]
    conn.execute(
        "update public.journeys set current_route_version_id = %s where id = %s", (version, journey)
    )
    if position is not None:
        conn.execute(
            "update public.journeys set last_position = %s::extensions.geography, "
            "last_position_at = now() - interval '5 seconds', "
            "last_device_ts = now() - interval '5 seconds' where id = %s",
            (f"POINT({position[0]} {position[1]})", journey),
        )
    return {
        "op": op,
        "journey": journey,
        "template": template,
        "service": service,
        "bus": bus,
        "version": version,
        "stops": stops,
        "journey_stops": journey_stops,
        "ctx": OperatorContext(tenants[owner], None, op, "Test Operator", "owner"),
    }
