"""Versioned route plans. Every assigned route is an immutable, numbered version."""

import logging
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.auth.deps import OperatorContext
from app.domain import journeys, lifecycle, routes, routing, stop_plan, validation
from app.domain.audit import record_event
from app.domain.errors import Conflict
from app.providers.routing.base import RoutingError, RoutingProvider

logger = logging.getLogger(__name__)

VERSION_SELECT = """
select v.id, v.journey_id, v.version, v.distance_m, v.duration_s, v.reason, v.source,
       v.details, v.created_by, v.created_at,
       v.id = j.current_route_version_id as is_current,
       extensions.st_asgeojson(
         extensions.st_simplify(v.geometry::extensions.geometry, 0.0005))::jsonb -> 'coordinates'
         as coordinates
from public.route_versions v
join public.journeys j on j.id = v.journey_id
"""


def list_versions(conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID) -> list:
    journeys.get_journey(conn, ctx, journey_id)
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            VERSION_SELECT + " where v.journey_id = %s and v.operator_id = %s order by v.version",
            (journey_id, ctx.operator_id),
        ).fetchall()


def create_version(
    conn: psycopg.Connection,
    *,
    operator_id: uuid.UUID,
    journey_id: uuid.UUID,
    coordinates: list[tuple[float, float]],
    distance_m: float | None,
    duration_s: float | None,
    reason: str,
    source: str,
    details: dict | None = None,
    created_by: uuid.UUID | None = None,
) -> dict:
    """Append the next route version and make it the journey's current route.

    The caller must hold the journey row lock, so version numbers never collide.
    """
    number = conn.execute(
        "select coalesce(max(version), 0) + 1 from public.route_versions where journey_id = %s",
        (journey_id,),
    ).fetchone()[0]
    version_id = conn.execute(
        "insert into public.route_versions (operator_id, journey_id, version, geometry, "
        "distance_m, duration_s, reason, source, details, created_by) "
        "values (%s, %s, %s, %s::extensions.geography, %s, %s, %s, %s, %s, %s) returning id",
        (
            operator_id,
            journey_id,
            number,
            routes.linestring_wkt(coordinates),
            distance_m,
            duration_s,
            reason,
            source,
            Jsonb(details or {}),
            created_by,
        ),
    ).fetchone()[0]
    conn.execute(
        "update public.journeys set current_route_version_id = %s where id = %s",
        (version_id, journey_id),
    )
    return {"id": version_id, "version": number}


def planned_waypoints(conn: psycopg.Connection, journey_id: uuid.UUID) -> list[dict]:
    """Origin, the active intermediate stops in road order, then the destination."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            select s.id::text as stop_id, s.name, s.role, s.chainage_m,
                   extensions.st_x(s.location::extensions.geometry) as lng,
                   extensions.st_y(s.location::extensions.geometry) as lat,
                   js.id is not null as active
            from public.journeys j
            join public.route_template_stops s on s.route_template_id = j.route_template_id
            left join public.journey_stops js
              on js.route_template_stop_id = s.id and js.journey_id = j.id
            where j.id = %s and (s.role <> 'intermediate' or js.id is not null)
            order by case s.role when 'origin' then 0 when 'destination' then 2 else 1 end,
                     s.chainage_m
            """,
            (journey_id,),
        ).fetchall()


def assign(
    conn: psycopg.Connection,
    ctx: OperatorContext,
    provider: RoutingProvider,
    journey_id: uuid.UUID,
) -> dict:
    """Operator confirms the plan: route through every active stop becomes version N."""
    journey = journeys.get_journey(conn, ctx, journey_id, lock=True)
    lifecycle.check_transition(journey["status"], "ready", ctx.role)
    issues = stop_plan.validate_journey(conn, ctx, journey_id)
    if validation.has_errors(issues):
        raise Conflict(
            "The journey plan has problems that must be fixed first.",
            details={
                "issues": [
                    {"code": i.code, "message": i.message} for i in issues if i.severity == "error"
                ]
            },
        )

    waypoints = planned_waypoints(conn, journey_id)
    details: dict = {
        "route_template_id": str(journey["route_template_id"]),
        "waypoints": [
            {"stop_id": w["stop_id"], "name": w["name"], "role": w["role"]} for w in waypoints
        ],
    }
    try:
        result = routing.route(conn, provider, [(w["lng"], w["lat"]) for w in waypoints])[0]
        coordinates = result.coordinates
        distance_m, duration_s = result.distance_m, result.duration_s
        details.update(
            provider=result.provider,
            attribution=result.metadata.get("attribution"),
            waypoint_indices=result.waypoint_indices,
            legs=[
                {"distance_m": leg.distance_m, "duration_s": leg.duration_s} for leg in result.legs
            ],
        )
    except RoutingError as exc:
        # The approved template geometry is always a valid route for this journey.
        logger.warning("assign fell back to template geometry: %s", type(exc).__name__)
        coordinates = routes.full_coordinates(conn, journey["route_template_id"])
        template = routes.get_template(conn, ctx, journey["route_template_id"])
        distance_m, duration_s = template["distance_m"], template["duration_s"]
        details.update(provider=template["provider"], fallback="template_geometry")

    version = create_version(
        conn,
        operator_id=ctx.operator_id,
        journey_id=journey_id,
        coordinates=coordinates,
        distance_m=distance_m,
        duration_s=duration_s,
        reason="Route assigned by operator",
        source="operator_initial",
        details=details,
        created_by=ctx.user_id,
    )
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        journey_id=journey_id,
        event_type="route_assigned",
        payload={"version": version["version"], "distance_m": distance_m},
    )
    lifecycle.apply_status(conn, ctx, journey_id, journey["status"], "ready")
    return journeys.get_journey(conn, ctx, journey_id)
