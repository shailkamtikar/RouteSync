"""Buses and services. Every query is filtered by the caller's operator_id."""

import uuid
from typing import Any

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.auth.deps import OperatorContext
from app.domain.audit import record_event
from app.domain.errors import Conflict, Invalid, NotFound
from app.schemas.fleet import BusCreate, BusUpdate, LatLng, ServiceCreate, ServiceUpdate

BUS_COLUMNS = "id, registration, capacity, vehicle_constraints, status, created_at, updated_at"
SERVICE_COLUMNS = (
    "id, origin_name, destination_name, status, created_at, updated_at, "
    "extensions.st_y(origin_location::extensions.geometry) as origin_lat, "
    "extensions.st_x(origin_location::extensions.geometry) as origin_lng, "
    "extensions.st_y(destination_location::extensions.geometry) as destination_lat, "
    "extensions.st_x(destination_location::extensions.geometry) as destination_lng"
)


def _point(location: LatLng | None) -> str | None:
    return None if location is None else f"POINT({location.lng} {location.lat})"


def _service_row(row: dict[str, Any]) -> dict[str, Any]:
    for prefix in ("origin", "destination"):
        lat, lng = row.pop(f"{prefix}_lat"), row.pop(f"{prefix}_lng")
        row[f"{prefix}_location"] = None if lat is None else {"lat": lat, "lng": lng}
    return row


def _check_version(current: dict[str, Any], expected) -> None:
    if expected is not None and current["updated_at"] != expected:
        raise Conflict("The record was changed by someone else. Reload and try again.")


# ------------------------------------------------------------------ buses


def list_buses(conn: psycopg.Connection, ctx: OperatorContext, include_archived: bool) -> list:
    query = f"select {BUS_COLUMNS} from public.buses where operator_id = %s"
    if not include_archived:
        query += " and status = 'active'"
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(query + " order by registration", (ctx.operator_id,)).fetchall()


def get_bus(conn: psycopg.Connection, ctx: OperatorContext, bus_id: uuid.UUID, lock=False) -> dict:
    query = f"select {BUS_COLUMNS} from public.buses where id = %s and operator_id = %s"
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            query + (" for update" if lock else ""), (bus_id, ctx.operator_id)
        ).fetchone()
    if row is None:
        raise NotFound("Bus not found")
    return row


def create_bus(conn: psycopg.Connection, ctx: OperatorContext, data: BusCreate) -> dict:
    try:
        with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                "insert into public.buses (operator_id, registration, capacity, "
                f"vehicle_constraints) values (%s, %s, %s, %s) returning {BUS_COLUMNS}",
                (
                    ctx.operator_id,
                    data.registration,
                    data.capacity,
                    Jsonb(data.vehicle_constraints),
                ),
            ).fetchone()
    except pg_errors.UniqueViolation:
        raise Conflict("A bus with this registration already exists") from None
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type="bus_created",
        entity_type="bus",
        entity_id=row["id"],
        payload={"registration": row["registration"], "capacity": row["capacity"]},
    )
    return row


def update_bus(
    conn: psycopg.Connection, ctx: OperatorContext, bus_id: uuid.UUID, data: BusUpdate
) -> dict:
    current = get_bus(conn, ctx, bus_id, lock=True)
    _check_version(current, data.expected_updated_at)
    changes = data.model_dump(exclude_unset=True, exclude={"expected_updated_at"})
    changes = {k: v for k, v in changes.items() if v is not None}
    if not changes:
        return current
    values = {**changes}
    if "vehicle_constraints" in values:
        values["vehicle_constraints"] = Jsonb(values["vehicle_constraints"])
    assignments = ", ".join(f"{column} = %s" for column in values)
    try:
        with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                f"update public.buses set {assignments} where id = %s and operator_id = %s "
                f"returning {BUS_COLUMNS}",
                (*values.values(), bus_id, ctx.operator_id),
            ).fetchone()
    except pg_errors.UniqueViolation:
        raise Conflict("A bus with this registration already exists") from None
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type="bus_updated",
        entity_type="bus",
        entity_id=bus_id,
        payload={"fields": sorted(changes)},
    )
    return row


def remove_bus(conn: psycopg.Connection, ctx: OperatorContext, bus_id: uuid.UUID) -> str:
    """Delete the bus, or archive it when journeys reference it."""
    get_bus(conn, ctx, bus_id, lock=True)
    used = conn.execute(
        "select exists (select 1 from public.journeys where bus_id = %s)", (bus_id,)
    ).fetchone()[0]
    if used:
        conn.execute(
            "update public.buses set status = 'archived' where id = %s and operator_id = %s",
            (bus_id, ctx.operator_id),
        )
        result = "archived"
    else:
        conn.execute(
            "delete from public.buses where id = %s and operator_id = %s", (bus_id, ctx.operator_id)
        )
        result = "deleted"
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type=f"bus_{result}",
        entity_type="bus",
        entity_id=bus_id,
    )
    return result


# ------------------------------------------------------------------ services


def list_services(conn: psycopg.Connection, ctx: OperatorContext, include_archived: bool) -> list:
    query = f"select {SERVICE_COLUMNS} from public.services where operator_id = %s"
    if not include_archived:
        query += " and status = 'active'"
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            query + " order by origin_name, destination_name", (ctx.operator_id,)
        ).fetchall()
    return [_service_row(row) for row in rows]


def get_service(
    conn: psycopg.Connection, ctx: OperatorContext, service_id: uuid.UUID, lock=False
) -> dict:
    query = f"select {SERVICE_COLUMNS} from public.services where id = %s and operator_id = %s"
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            query + (" for update" if lock else ""), (service_id, ctx.operator_id)
        ).fetchone()
    if row is None:
        raise NotFound("Service not found")
    return _service_row(row)


def create_service(conn: psycopg.Connection, ctx: OperatorContext, data: ServiceCreate) -> dict:
    service_id = conn.execute(
        "insert into public.services (operator_id, origin_name, destination_name, "
        "origin_location, destination_location) values (%s, %s, %s, "
        "%s::extensions.geography, %s::extensions.geography) returning id",
        (
            ctx.operator_id,
            data.origin_name,
            data.destination_name,
            _point(data.origin_location),
            _point(data.destination_location),
        ),
    ).fetchone()[0]
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type="service_created",
        entity_type="service",
        entity_id=service_id,
        payload={"origin": data.origin_name, "destination": data.destination_name},
    )
    return get_service(conn, ctx, service_id)


def update_service(
    conn: psycopg.Connection, ctx: OperatorContext, service_id: uuid.UUID, data: ServiceUpdate
) -> dict:
    current = get_service(conn, ctx, service_id, lock=True)
    _check_version(current, data.expected_updated_at)
    changes = data.model_dump(exclude_unset=True, exclude={"expected_updated_at"})
    changes = {k: v for k, v in changes.items() if v is not None}
    if not changes:
        return current
    origin = changes.get("origin_name", current["origin_name"])
    destination = changes.get("destination_name", current["destination_name"])
    if origin.lower() == destination.lower():
        raise Invalid("origin and destination must be different")
    assignments, params = [], []
    for column, value in changes.items():
        if column.endswith("_location"):
            assignments.append(f"{column} = %s::extensions.geography")
            params.append(f"POINT({value['lng']} {value['lat']})")
        else:
            assignments.append(f"{column} = %s")
            params.append(value)
    conn.execute(
        f"update public.services set {', '.join(assignments)} where id = %s and operator_id = %s",
        (*params, service_id, ctx.operator_id),
    )
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type="service_updated",
        entity_type="service",
        entity_id=service_id,
        payload={"fields": sorted(changes)},
    )
    return get_service(conn, ctx, service_id)


def remove_service(conn: psycopg.Connection, ctx: OperatorContext, service_id: uuid.UUID) -> str:
    """Delete the service, or archive it when journeys or route templates reference it."""
    get_service(conn, ctx, service_id, lock=True)
    used = conn.execute(
        "select exists (select 1 from public.journeys where service_id = %s) "
        "or exists (select 1 from public.route_templates where service_id = %s)",
        (service_id, service_id),
    ).fetchone()[0]
    if used:
        conn.execute(
            "update public.services set status = 'archived' where id = %s and operator_id = %s",
            (service_id, ctx.operator_id),
        )
        result = "archived"
    else:
        conn.execute(
            "delete from public.services where id = %s and operator_id = %s",
            (service_id, ctx.operator_id),
        )
        result = "deleted"
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type=f"service_{result}",
        entity_type="service",
        entity_id=service_id,
    )
    return result
