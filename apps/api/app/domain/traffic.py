"""Simulated traffic incidents on a route option (operator-scoped)."""

import uuid
from datetime import datetime, timedelta

import psycopg
from psycopg.rows import dict_row

from app.auth.deps import OperatorContext
from app.domain import routes
from app.domain.audit import record_event
from app.domain.errors import Invalid, NotFound
from app.eta.traffic import Incident
from app.schemas.traffic import TrafficIncidentCreate

INCIDENT_SELECT = """
select i.id, i.route_template_id, i.kind, i.multiplier, i.from_km, i.to_km, i.description,
       i.simulated, i.starts_at, i.ends_at,
       extensions.st_x(i.from_point::extensions.geometry) as from_lng,
       extensions.st_y(i.from_point::extensions.geometry) as from_lat,
       extensions.st_x(i.to_point::extensions.geometry) as to_lng,
       extensions.st_y(i.to_point::extensions.geometry) as to_lat
from public.traffic_incidents i
"""


def create_incident(
    conn: psycopg.Connection,
    ctx: OperatorContext,
    template_id: uuid.UUID,
    data: TrafficIncidentCreate,
) -> dict:
    template = routes.get_template(conn, ctx, template_id)
    if template["status"] == "unresolved" or not template["distance_m"]:
        raise Invalid("This route option has no generated route yet")
    length_km = template["distance_m"] / 1000
    if data.to_km > length_km + 0.5:
        raise Invalid(f"This route is {length_km:.0f} km long")
    # Start and end use the database clock, the same clock that later decides what is active.
    start = conn.execute("select clock_timestamp()").fetchone()[0]
    ends = start + timedelta(minutes=data.duration_minutes) if data.duration_minutes else None
    incident_id = conn.execute(
        """
        insert into public.traffic_incidents
          (operator_id, route_template_id, kind, multiplier, from_point, to_point,
           from_km, to_km, description, starts_at, ends_at, created_by)
        select %(operator)s, t.id, %(kind)s, %(multiplier)s,
               extensions.st_lineinterpolatepoint(t.geometry::extensions.geometry,
                 least(%(from_km)s * 1000 / t.distance_m, 1))::extensions.geography,
               extensions.st_lineinterpolatepoint(t.geometry::extensions.geometry,
                 least(%(to_km)s * 1000 / t.distance_m, 1))::extensions.geography,
               %(from_km)s, %(to_km)s, %(description)s, %(start)s, %(ends)s, %(user)s
        from public.route_templates t where t.id = %(template)s and t.operator_id = %(operator)s
        returning id
        """,
        {
            "operator": ctx.operator_id,
            "kind": data.kind,
            "multiplier": 1.0 if data.kind == "closure" else data.multiplier,
            "from_km": data.from_km,
            "to_km": data.to_km,
            "description": data.description,
            "start": start,
            "ends": ends,
            "user": ctx.user_id,
            "template": template_id,
        },
    ).fetchone()[0]
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type="traffic_incident_created",
        entity_type="traffic_incident",
        entity_id=incident_id,
        payload={
            "kind": data.kind,
            "from_km": data.from_km,
            "to_km": data.to_km,
            "multiplier": data.multiplier,
            "simulated": True,
        },
    )
    return get_incident(conn, ctx, incident_id)


def get_incident(conn: psycopg.Connection, ctx: OperatorContext, incident_id: uuid.UUID) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            INCIDENT_SELECT + " where i.id = %s and i.operator_id = %s",
            (incident_id, ctx.operator_id),
        ).fetchone()
    if row is None:
        raise NotFound("Traffic incident not found")
    return row


def list_incidents(
    conn: psycopg.Connection, ctx: OperatorContext, template_id: uuid.UUID, active_only: bool
) -> list:
    routes.get_template(conn, ctx, template_id)
    query = INCIDENT_SELECT + " where i.route_template_id = %s and i.operator_id = %s"
    if active_only:
        query += (
            " and i.starts_at <= clock_timestamp()"
            " and (i.ends_at is null or i.ends_at > clock_timestamp())"
        )
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(query + " order by i.from_km", (template_id, ctx.operator_id)).fetchall()


def end_incident(conn: psycopg.Connection, ctx: OperatorContext, incident_id: uuid.UUID) -> None:
    get_incident(conn, ctx, incident_id)
    conn.execute(
        "update public.traffic_incidents "
        "set ends_at = greatest(clock_timestamp(), starts_at + interval '1 ms') "
        "where id = %s and operator_id = %s and (ends_at is null or ends_at > clock_timestamp())",
        (incident_id, ctx.operator_id),
    )
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type="traffic_incident_ended",
        entity_type="traffic_incident",
        entity_id=incident_id,
    )


def incidents_for_template(
    conn: psycopg.Connection, operator_id: uuid.UUID, template_id: uuid.UUID
) -> list[Incident]:
    """Incidents that may currently matter for journeys on this route option."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            INCIDENT_SELECT + " where i.route_template_id = %s and i.operator_id = %s "
            "and (i.ends_at is null or i.ends_at > clock_timestamp() - interval '1 minute')",
            (template_id, operator_id),
        ).fetchall()
    return [
        Incident(
            incident_id=str(row["id"]),
            kind=row["kind"],
            multiplier=row["multiplier"],
            from_point=(row["from_lng"], row["from_lat"]),
            to_point=(row["to_lng"], row["to_lat"]),
            starts_at=row["starts_at"],
            ends_at=row["ends_at"],
            simulated=row["simulated"],
            description=row["description"],
        )
        for row in rows
    ]


def database_now(conn: psycopg.Connection) -> datetime:
    """The database's wall clock. Incident times are compared against this clock only."""
    return conn.execute("select clock_timestamp()").fetchone()[0]
