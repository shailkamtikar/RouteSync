"""Stops of a route template (route-specific), OSM stop suggestions, booking stop matching."""

import hashlib
import json
import logging
import uuid
from functools import lru_cache
from typing import Annotated

import psycopg
from fastapi import Depends
from psycopg import errors as pg_errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.auth.deps import OperatorContext
from app.config import get_settings
from app.domain import journeys, routes
from app.domain.audit import record_event
from app.domain.errors import Conflict, Invalid, NotFound
from app.providers.places.base import PlacesProvider, PlacesUnavailable
from app.providers.places.overpass import OverpassPlacesProvider
from app.schemas.routes import StopCreate, StopUpdate

logger = logging.getLogger(__name__)

STOP_SELECT = """
select s.id, s.route_template_id, s.name, s.chainage_m, s.kind, s.role, s.source,
       extensions.st_y(s.location::extensions.geometry) as lat,
       extensions.st_x(s.location::extensions.geometry) as lng
from public.route_template_stops s
"""


@lru_cache
def _default_places_provider() -> PlacesProvider:
    return OverpassPlacesProvider()


def get_places_provider() -> PlacesProvider:
    return _default_places_provider()


Places = Annotated[PlacesProvider, Depends(get_places_provider)]


def _row(row: dict) -> dict:
    row["location"] = {"lat": row.pop("lat"), "lng": row.pop("lng")}
    return row


def list_stops(conn: psycopg.Connection, ctx: OperatorContext, template_id: uuid.UUID) -> list:
    routes.get_template(conn, ctx, template_id)
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            STOP_SELECT + " where s.route_template_id = %s and s.operator_id = %s "
            "order by s.chainage_m nulls last, s.name",
            (template_id, ctx.operator_id),
        ).fetchall()
    return [_row(row) for row in rows]


def get_stop(conn: psycopg.Connection, ctx: OperatorContext, stop_id: uuid.UUID) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            STOP_SELECT + " where s.id = %s and s.operator_id = %s", (stop_id, ctx.operator_id)
        ).fetchone()
    if row is None:
        raise NotFound("Stop not found")
    return _row(row)


def _ready_template(conn, ctx: OperatorContext, template_id: uuid.UUID) -> dict:
    template = routes.get_template(conn, ctx, template_id, lock=True)
    if template["status"] != "ready":
        raise Invalid("Generate the route for this option before adding stops")
    return template


def create_stop(
    conn: psycopg.Connection, ctx: OperatorContext, template_id: uuid.UUID, data: StopCreate
) -> dict:
    """Add a stop to one route option. The stop must lie on that option's corridor."""
    _ready_template(conn, ctx, template_id)
    point = f"POINT({data.location.lng} {data.location.lat})"
    width = get_settings().corridor_width_m
    on_corridor = conn.execute(
        "select extensions.st_dwithin(geometry, %s::extensions.geography, %s) "
        "from public.route_templates where id = %s",
        (point, width, template_id),
    ).fetchone()[0]
    if not on_corridor:
        raise Invalid(
            f"{data.name} is more than {width / 1000:g} km from this route, "
            "so it cannot be a stop on it"
        )
    try:
        with conn.transaction():
            stop_id = conn.execute(
                "insert into public.route_template_stops (operator_id, route_template_id, name, "
                "location, kind, source, chainage_m) "
                "select %s, t.id, %s, %s::extensions.geography, %s, %s, "
                "  extensions.st_linelocatepoint(t.geometry::extensions.geometry, "
                "    (%s::extensions.geography)::extensions.geometry) * t.distance_m "
                "from public.route_templates t where t.id = %s returning id",
                (ctx.operator_id, data.name, point, data.kind, data.source, point, template_id),
            ).fetchone()[0]
    except pg_errors.UniqueViolation:
        raise Conflict("This route option already has a stop with that name") from None
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type="route_stop_created",
        entity_type="route_template_stop",
        entity_id=stop_id,
        payload={"name": data.name, "kind": data.kind, "source": data.source},
    )
    return get_stop(conn, ctx, stop_id)


def update_stop(
    conn: psycopg.Connection, ctx: OperatorContext, stop_id: uuid.UUID, data: StopUpdate
) -> dict:
    current = get_stop(conn, ctx, stop_id)
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not changes:
        return current
    if current["role"] != "intermediate":
        raise Conflict("The origin and destination stops follow the service and cannot be edited")
    if changes.get("kind") == "pass_through":
        used = conn.execute(
            "select exists (select 1 from public.journey_stops where route_template_stop_id = %s)",
            (stop_id,),
        ).fetchone()[0]
        if used:
            raise Conflict("This stop is an active stop on a journey")
    assignments = ", ".join(f"{column} = %s" for column in changes)
    try:
        with conn.transaction():
            conn.execute(
                f"update public.route_template_stops set {assignments} "
                "where id = %s and operator_id = %s",
                (*changes.values(), stop_id, ctx.operator_id),
            )
    except pg_errors.UniqueViolation:
        raise Conflict("This route option already has a stop with that name") from None
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type="route_stop_updated",
        entity_type="route_template_stop",
        entity_id=stop_id,
        payload={"fields": sorted(changes)},
    )
    return get_stop(conn, ctx, stop_id)


def remove_stop(conn: psycopg.Connection, ctx: OperatorContext, stop_id: uuid.UUID) -> None:
    current = get_stop(conn, ctx, stop_id)
    if current["role"] != "intermediate":
        raise Conflict("The origin and destination stops cannot be removed")
    used = conn.execute(
        "select exists (select 1 from public.journey_stops where route_template_stop_id = %s)",
        (stop_id,),
    ).fetchone()[0]
    if used:
        raise Conflict("This stop is an active stop on a journey and cannot be removed")
    conn.execute(
        "update public.bookings set pickup_stop_id = null where pickup_stop_id = %s", (stop_id,)
    )
    conn.execute(
        "update public.bookings set drop_stop_id = null where drop_stop_id = %s", (stop_id,)
    )
    conn.execute(
        "delete from public.route_template_stops where id = %s and operator_id = %s",
        (stop_id, ctx.operator_id),
    )
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type="route_stop_deleted",
        entity_type="route_template_stop",
        entity_id=stop_id,
    )


# ------------------------------------------------------------------ OSM suggestions


def stop_candidates(
    conn: psycopg.Connection,
    ctx: OperatorContext,
    provider: PlacesProvider,
    template_id: uuid.UUID,
) -> dict:
    """Named OSM places on this route option's corridor that are not stops yet.

    A suggestion is only a suggestion: nothing becomes a stop until the operator adds it.
    """
    template = routes.get_template(conn, ctx, template_id)
    if template["status"] != "ready":
        raise Invalid("Generate the route for this option first")
    width = get_settings().corridor_width_m
    line = [(c[0], c[1]) for c in template["coordinates"]]
    key = hashlib.sha256(
        json.dumps([provider.name, width, [[round(a, 4), round(b, 4)] for a, b in line]]).encode()
    ).hexdigest()

    cached = conn.execute(
        "select response from public.places_cache where key = %s", (key,)
    ).fetchone()
    if cached:
        places = cached[0]
    else:
        try:
            found = provider.places_near_line(line, width)
        except PlacesUnavailable:
            return {
                "available": False,
                "message": "Place suggestions are unavailable right now. "
                "You can still add stops yourself.",
                "attribution": None,
                "candidates": [],
            }
        places = [
            {"name": p.name, "lng": p.lng, "lat": p.lat, "place_type": p.place_type} for p in found
        ]
        conn.execute(
            "insert into public.places_cache (key, response) values (%s, %s) "
            "on conflict (key) do update set response = excluded.response, created_at = now()",
            (key, Jsonb(places)),
        )

    # The database decides what is really on this corridor, and where along the route.
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "select p.name, p.lng, p.lat, p.place_type, "
            "  extensions.st_linelocatepoint(t.geometry::extensions.geometry, "
            "    extensions.st_setsrid(extensions.st_makepoint(p.lng, p.lat), 4326)) "
            "    * t.distance_m as chainage_m "
            "from jsonb_to_recordset(%s) as p(name text, lng float8, lat float8, place_type text) "
            "join public.route_templates t on t.id = %s "
            "where extensions.st_dwithin(t.geometry, extensions.st_setsrid("
            "    extensions.st_makepoint(p.lng, p.lat), 4326)::extensions.geography, %s) "
            "  and not exists (select 1 from public.route_template_stops s "
            "    where s.route_template_id = t.id and lower(btrim(s.name)) = lower(btrim(p.name))) "
            "order by chainage_m, p.name",
            (Jsonb(places), template_id, width),
        ).fetchall()
    seen: set[str] = set()
    candidates = []
    for row in rows:
        if row["name"].lower() in seen:
            continue
        seen.add(row["name"].lower())
        candidates.append(
            {
                "name": row["name"],
                "location": {"lat": row["lat"], "lng": row["lng"]},
                "place_type": row["place_type"],
                "chainage_m": row["chainage_m"],
            }
        )
    return {
        "available": True,
        "message": None,
        "attribution": provider.attribution,
        "candidates": candidates,
    }


# ------------------------------------------------------------------ booking stop matching


def resolve_booking_stops(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID
) -> dict:
    """Match each booking's pickup/drop stop name to a passenger stop of the journey's own
    route option. Names that do not match stay unresolved and are reported."""
    journey = journeys.get_journey(conn, ctx, journey_id)
    template_id = journey["route_template_id"]
    if template_id is None:
        raise Invalid("Choose a route option for this journey first")
    resolved = 0
    for kind in ("pickup", "drop"):
        resolved += conn.execute(
            f"update public.bookings b set {kind}_stop_id = s.id "
            "from public.route_template_stops s "
            "where b.journey_id = %s and b.operator_id = %s "
            "  and s.route_template_id = %s and s.kind = 'passenger_stop' "
            f"  and lower(btrim(s.name)) = lower(btrim(b.{kind}_stop_name)) "
            f"  and b.{kind}_stop_id is distinct from s.id",
            (journey_id, ctx.operator_id, template_id),
        ).rowcount
    with conn.cursor(row_factory=dict_row) as cur:
        unresolved = cur.execute(
            "select id as booking_id, reference, "
            "  case when pickup_stop_id is null then pickup_stop_name end as pickup_stop_name, "
            "  case when drop_stop_id is null then drop_stop_name end as drop_stop_name "
            "from public.bookings where journey_id = %s and operator_id = %s "
            "  and status = 'confirmed' and (pickup_stop_id is null or drop_stop_id is null) "
            "order by reference",
            (journey_id, ctx.operator_id),
        ).fetchall()
    return {"resolved": resolved, "unresolved": unresolved}
