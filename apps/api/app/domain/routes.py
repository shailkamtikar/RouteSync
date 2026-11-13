"""Route templates: operator-defined route options (corridors) for a service.

Each template has its own geometry and its own stop list. Stops of one route option are
never mixed with another's.
"""

import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.auth.deps import OperatorContext
from app.config import get_settings
from app.domain import fleet, journeys, routing
from app.domain.audit import record_event
from app.domain.errors import Conflict, Invalid, NotFound
from app.providers.routing.base import RoutingError, RoutingProvider
from app.schemas.routes import RouteTemplateCreate, RouteTemplateUpdate

TEMPLATE_SELECT = """
select t.id, t.service_id, t.name, t.version, t.via_points, t.profile, t.status,
       t.distance_m, t.duration_s, t.provider,
       t.provider_metadata ->> 'attribution' as attribution,
       coalesce(extensions.st_asgeojson(
         extensions.st_simplify(t.geometry::extensions.geometry, 0.0005))::jsonb -> 'coordinates',
         '[]'::jsonb) as coordinates,
       (select count(*) from public.route_template_stops s
         where s.route_template_id = t.id)::int as stop_count,
       t.created_at, t.updated_at
from public.route_templates t
"""


def linestring_wkt(coordinates) -> str:
    return "LINESTRING(" + ", ".join(f"{lng:.6f} {lat:.6f}" for lng, lat in coordinates) + ")"


def list_templates(
    conn: psycopg.Connection, ctx: OperatorContext, service_id: uuid.UUID, include_archived: bool
) -> list:
    fleet.get_service(conn, ctx, service_id)
    query = TEMPLATE_SELECT + " where t.service_id = %s and t.operator_id = %s"
    if not include_archived:
        query += " and t.status <> 'archived'"
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            query + " order by t.name, t.version", (service_id, ctx.operator_id)
        ).fetchall()


def get_template(
    conn: psycopg.Connection, ctx: OperatorContext, template_id: uuid.UUID, lock: bool = False
) -> dict:
    if lock:
        conn.execute(
            "select 1 from public.route_templates where id = %s and operator_id = %s for update",
            (template_id, ctx.operator_id),
        )
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            TEMPLATE_SELECT + " where t.id = %s and t.operator_id = %s",
            (template_id, ctx.operator_id),
        ).fetchone()
    if row is None:
        raise NotFound("Route option not found")
    return row


def full_coordinates(conn: psycopg.Connection, template_id: uuid.UUID) -> list[tuple[float, float]]:
    """Unsimplified geometry, for route calculations."""
    row = conn.execute(
        "select extensions.st_asgeojson(geometry::extensions.geometry)::jsonb -> 'coordinates' "
        "from public.route_templates where id = %s",
        (template_id,),
    ).fetchone()
    return [(c[0], c[1]) for c in (row[0] or [])] if row else []


def _ensure_name_free(conn, service_id: uuid.UUID, name: str, except_id=None) -> None:
    clash = conn.execute(
        "select 1 from public.route_templates where service_id = %s and status <> 'archived' "
        "and lower(name) = lower(%s) and id is distinct from %s",
        (service_id, name, except_id),
    ).fetchone()
    if clash:
        raise Conflict("This service already has a route option with that name")


def _refresh_stops(conn, operator_id, template_id: uuid.UUID, service: dict) -> None:
    """Keep the origin/destination stops in step with the service and recompute chainage."""
    for role, prefix in (("origin", "origin"), ("destination", "destination")):
        location = service[f"{prefix}_location"]
        point = f"POINT({location['lng']} {location['lat']})"
        updated = conn.execute(
            "update public.route_template_stops set location = %s::extensions.geography, "
            "name = %s where route_template_id = %s and role = %s",
            (point, service[f"{prefix}_name"], template_id, role),
        ).rowcount
        if not updated:
            # A manually added stop with the endpoint's name becomes the endpoint.
            conn.execute(
                "delete from public.route_template_stops where route_template_id = %s "
                "and lower(btrim(name)) = lower(%s) "
                "and not exists (select 1 from public.journey_stops j "
                "                where j.route_template_stop_id = route_template_stops.id)",
                (template_id, service[f"{prefix}_name"]),
            )
            conn.execute(
                "insert into public.route_template_stops (operator_id, route_template_id, name, "
                "location, kind, role) values (%s, %s, %s, %s::extensions.geography, "
                "'passenger_stop', %s)",
                (operator_id, template_id, service[f"{prefix}_name"], point, role),
            )
    conn.execute(
        "update public.route_template_stops s set chainage_m = case s.role "
        "  when 'origin' then 0 "
        "  when 'destination' then t.distance_m "
        "  else extensions.st_linelocatepoint(t.geometry::extensions.geometry, "
        "         s.location::extensions.geometry) * t.distance_m end "
        "from public.route_templates t where t.id = s.route_template_id and t.id = %s",
        (template_id,),
    )


def generate_geometry(
    conn: psycopg.Connection,
    ctx: OperatorContext,
    provider: RoutingProvider,
    template_id: uuid.UUID,
) -> dict:
    """Ask the routing provider for this option's road geometry and store it."""
    template = get_template(conn, ctx, template_id, lock=True)
    service = fleet.get_service(conn, ctx, template["service_id"])
    if not service["origin_location"] or not service["destination_location"]:
        raise Invalid("Set the origin and destination coordinates on the service first")
    waypoints = (
        [(service["origin_location"]["lng"], service["origin_location"]["lat"])]
        + [(point["lng"], point["lat"]) for point in template["via_points"]]
        + [(service["destination_location"]["lng"], service["destination_location"]["lat"])]
    )
    result = routing.route(conn, provider, waypoints, profile=template["profile"])[0]
    width = get_settings().corridor_width_m
    conn.execute(
        "update public.route_templates set "
        "  geometry = %(wkt)s::extensions.geography, "
        "  corridor = extensions.st_buffer(extensions.st_simplify("
        "    %(wkt)s::extensions.geometry, 0.001)::extensions.geography, %(width)s), "
        "  distance_m = %(distance)s, duration_s = %(duration)s, provider = %(provider)s, "
        "  provider_metadata = %(metadata)s, status = 'ready' "
        "where id = %(id)s and operator_id = %(operator)s",
        {
            "wkt": linestring_wkt(result.coordinates),
            "width": width,
            "distance": result.distance_m,
            "duration": result.duration_s,
            "provider": result.provider,
            "metadata": Jsonb(
                {
                    **result.metadata,
                    "waypoint_indices": result.waypoint_indices,
                    "legs": [
                        {"distance_m": leg.distance_m, "duration_s": leg.duration_s}
                        for leg in result.legs
                    ],
                    "corridor_width_m": width,
                }
            ),
            "id": template_id,
            "operator": ctx.operator_id,
        },
    )
    _refresh_stops(conn, ctx.operator_id, template_id, service)
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type="route_template_generated",
        entity_type="route_template",
        entity_id=template_id,
        payload={"distance_m": result.distance_m, "provider": result.provider},
    )
    return get_template(conn, ctx, template_id)


def _try_generate(conn, ctx, provider, template_id) -> tuple[dict, str | None]:
    """Generate geometry; on provider failure keep the template and report the reason."""
    try:
        with conn.transaction():
            return generate_geometry(conn, ctx, provider, template_id), None
    except (RoutingError, Invalid) as exc:
        message = exc.message if isinstance(exc, Invalid) else str(exc)
        return get_template(conn, ctx, template_id), message


def create_template(
    conn: psycopg.Connection,
    ctx: OperatorContext,
    provider: RoutingProvider,
    service_id: uuid.UUID,
    data: RouteTemplateCreate,
) -> tuple[dict, str | None]:
    service = fleet.get_service(conn, ctx, service_id)
    if service["status"] != "active":
        raise Invalid("Service is archived")
    _ensure_name_free(conn, service_id, data.name)
    template_id = conn.execute(
        "insert into public.route_templates (operator_id, service_id, name, via_points, profile) "
        "values (%s, %s, %s, %s, %s) returning id",
        (
            ctx.operator_id,
            service_id,
            data.name,
            Jsonb([point.model_dump() for point in data.via_points]),
            data.profile,
        ),
    ).fetchone()[0]
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type="route_template_created",
        entity_type="route_template",
        entity_id=template_id,
        payload={"name": data.name, "via_points": len(data.via_points)},
    )
    return _try_generate(conn, ctx, provider, template_id)


def update_template(
    conn: psycopg.Connection,
    ctx: OperatorContext,
    provider: RoutingProvider,
    template_id: uuid.UUID,
    data: RouteTemplateUpdate,
) -> tuple[dict, str | None, list[str]]:
    """Rename in place. A change of road (via-points or profile) on a template that journeys
    already use creates a new version, so those journeys keep their original geometry."""
    current = get_template(conn, ctx, template_id, lock=True)
    if current["status"] == "archived":
        raise Conflict("An archived route option cannot be edited")
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not changes:
        return current, None, []
    if "name" in changes:
        _ensure_name_free(conn, current["service_id"], changes["name"], except_id=template_id)
    road_changed = ("via_points" in changes and changes["via_points"] != current["via_points"]) or (
        "profile" in changes and changes["profile"] != current["profile"]
    )
    in_use = conn.execute(
        "select exists (select 1 from public.journeys where route_template_id = %s)",
        (template_id,),
    ).fetchone()[0]
    warnings: list[str] = []
    target_id = template_id

    if road_changed and in_use:
        target_id = conn.execute(
            "insert into public.route_templates (operator_id, service_id, name, version, "
            "via_points, profile) values (%s, %s, %s, %s, %s, %s) returning id",
            (
                ctx.operator_id,
                current["service_id"],
                changes.get("name", current["name"]),
                current["version"] + 1,
                Jsonb(changes.get("via_points", current["via_points"])),
                changes.get("profile", current["profile"]),
            ),
        ).fetchone()[0]
        conn.execute(
            "update public.route_templates set status = 'archived' where id = %s", (template_id,)
        )
        conn.execute(
            "insert into public.route_template_stops (operator_id, route_template_id, name, "
            "location, kind, source, role) select operator_id, %s, name, location, kind, source, "
            "role from public.route_template_stops where route_template_id = %s "
            "and role = 'intermediate'",
            (target_id, template_id),
        )
        warnings.append("new_version_created")
    else:
        assignments, params = [], []
        for column, value in changes.items():
            assignments.append(f"{column} = %s")
            params.append(Jsonb(value) if column == "via_points" else value)
        conn.execute(
            f"update public.route_templates set {', '.join(assignments)} "
            "where id = %s and operator_id = %s",
            (*params, template_id, ctx.operator_id),
        )

    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type="route_template_updated",
        entity_type="route_template",
        entity_id=target_id,
        payload={"fields": sorted(changes), "previous_version_id": str(template_id)},
    )
    if not road_changed:
        return get_template(conn, ctx, target_id), None, warnings

    template, error = _try_generate(conn, ctx, provider, target_id)
    if error is None:
        outside = stops_outside_corridor(conn, target_id)
        if outside:
            warnings.append("stops_outside_corridor: " + ", ".join(outside))
    return template, error, warnings


def stops_outside_corridor(conn: psycopg.Connection, template_id: uuid.UUID) -> list[str]:
    rows = conn.execute(
        "select s.name from public.route_template_stops s "
        "join public.route_templates t on t.id = s.route_template_id "
        "where t.id = %s and not extensions.st_dwithin(t.geometry, s.location, %s) order by 1",
        (template_id, get_settings().corridor_width_m),
    ).fetchall()
    return [row[0] for row in rows]


def remove_template(conn: psycopg.Connection, ctx: OperatorContext, template_id: uuid.UUID) -> str:
    get_template(conn, ctx, template_id, lock=True)
    in_use = conn.execute(
        "select exists (select 1 from public.journeys where route_template_id = %s)",
        (template_id,),
    ).fetchone()[0]
    if in_use:
        conn.execute(
            "update public.route_templates set status = 'archived' where id = %s", (template_id,)
        )
        result = "archived"
    else:
        conn.execute(
            "update public.bookings set pickup_stop_id = null where pickup_stop_id in "
            "(select id from public.route_template_stops where route_template_id = %s)",
            (template_id,),
        )
        conn.execute(
            "update public.bookings set drop_stop_id = null where drop_stop_id in "
            "(select id from public.route_template_stops where route_template_id = %s)",
            (template_id,),
        )
        conn.execute(
            "delete from public.route_template_stops where route_template_id = %s", (template_id,)
        )
        conn.execute("delete from public.route_templates where id = %s", (template_id,))
        result = "deleted"
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type=f"route_template_{result}",
        entity_type="route_template",
        entity_id=template_id,
    )
    return result


def select_for_journey(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID, template_id: uuid.UUID
) -> dict:
    """Choose the route option for a draft journey. Changing it clears the old stop plan,
    because stops belong to one route option only."""
    journey = journeys.get_journey(conn, ctx, journey_id, lock=True)
    if journey["status"] != "draft":
        raise Conflict("The route option can only be changed while the journey is a draft")
    template = get_template(conn, ctx, template_id)
    if template["service_id"] != journey["service_id"]:
        raise Invalid("This route option belongs to a different service")
    if template["status"] != "ready":
        raise Invalid("This route option has no generated route yet")
    if journey["route_template_id"] == template_id:
        return journey
    removed = conn.execute(
        "delete from public.journey_stops where journey_id = %s", (journey_id,)
    ).rowcount
    conn.execute(
        "update public.bookings set pickup_stop_id = null, drop_stop_id = null "
        "where journey_id = %s",
        (journey_id,),
    )
    conn.execute(
        "update public.journeys set route_template_id = %s, plan_needs_review = false "
        "where id = %s and operator_id = %s",
        (template_id, journey_id, ctx.operator_id),
    )
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        journey_id=journey_id,
        event_type="journey_route_selected",
        payload={
            "route_template_id": str(template_id),
            "previous_route_template_id": (
                str(journey["route_template_id"]) if journey["route_template_id"] else None
            ),
            "active_stops_cleared": removed,
        },
    )
    from app.domain import stops

    stops.resolve_booking_stops(conn, ctx, journey_id)
    return journeys.get_journey(conn, ctx, journey_id)
