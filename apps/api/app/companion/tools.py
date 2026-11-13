"""Read-only tools the assistant may call, bound to one journey.

Every tool takes the journey from a server-side binding, never from an argument. Results are
public-safe (no names, seats, phones, references), carry freshness and availability, and all
arithmetic is done here, not by the model.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.auth.deps import OperatorContext
from app.domain import stop_events
from app.domain.errors import Conflict
from app.eta import service as eta_service
from app.providers.llm.base import ToolSpec


@dataclass(frozen=True)
class Binding:
    """The journey a conversation is bound to. Set by the server from the tracking token."""

    journey_id: uuid.UUID
    operator_id: uuid.UUID

    @property
    def ctx(self) -> OperatorContext:
        return OperatorContext(None, None, self.operator_id, "", "owner")


@dataclass
class ToolResult:
    data: dict[str, Any]
    availability: str = "available"  # available | stale | unknown | not_public | not_on_route
    as_of: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {"data": self.data, "availability": self.availability, "as_of": self.as_of}
        if self.note:
            out["note"] = self.note
        return out


def _journey(conn, b: Binding) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "select j.status, j.timezone, j.departure_at, j.booking_eta_at, j.public_counts_enabled, "
            "       j.route_template_id, j.current_route_version_id, j.last_position_at, "
            "       s.origin_name, s.destination_name, t.name as route_name, "
            "       extensions.st_x(j.last_position::extensions.geometry) as lng, "
            "       extensions.st_y(j.last_position::extensions.geometry) as lat "
            "from public.journeys j join public.services s on s.id = j.service_id "
            "left join public.route_templates t on t.id = j.route_template_id "
            "where j.id = %s and j.operator_id = %s",
            (b.journey_id, b.operator_id),
        ).fetchone()


def _active_stops(conn, b: Binding) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "select s.name, s.role, js.sequence, js.status, js.pickup_count, js.drop_count, "
            "       js.arrived_at, js.departed_at, js.dwell_minutes, "
            "       extensions.st_x(s.location::extensions.geometry) as lng, "
            "       extensions.st_y(s.location::extensions.geometry) as lat "
            "from public.journey_stops js "
            "join public.route_template_stops s on s.id = js.route_template_stop_id "
            "where js.journey_id = %s and js.operator_id = %s order by js.sequence",
            (b.journey_id, b.operator_id),
        ).fetchall()


def _eta(conn, b: Binding) -> dict | None:
    try:
        return eta_service.current_snapshot(conn, b.ctx, b.journey_id)
    except Conflict:
        return None


def _find_stop(stops: list[dict], name: str) -> dict | None:
    wanted = name.strip().lower()
    return next((s for s in stops if s["name"].lower() == wanted), None)


def _availability(eta: dict | None) -> str:
    if eta is None:
        return "unknown"
    return "stale" if eta["flags"].get("stale") or eta["flags"].get("plan_based") else "available"


# ------------------------------------------------------------------ the tools


def get_journey_overview(conn, b: Binding) -> ToolResult:
    j = _journey(conn, b)
    return ToolResult(
        {
            "origin": j["origin_name"],
            "destination": j["destination_name"],
            "status": j["status"],
            "departure_at": j["departure_at"].isoformat(),
            "arrival_promised_at_booking": j["booking_eta_at"].isoformat(),
            "timezone": j["timezone"],
        }
    )


def get_route_summary(conn, b: Binding) -> ToolResult:
    j = _journey(conn, b)
    stops = _active_stops(conn, b)
    version = conn.execute(
        "select version, reason, source from public.route_versions where id = %s",
        (j["current_route_version_id"],),
    ).fetchone()
    return ToolResult(
        {
            "route_option": j["route_name"],
            "passenger_stops_in_order": [s["name"] for s in stops],
            "route_version": version[0] if version else None,
            "latest_route_change_reason": version[1] if version else None,
            "route_changed_during_journey": bool(version and version[2] != "operator_initial"),
        }
    )


def get_route_geography(conn, b: Binding) -> ToolResult:
    j = _journey(conn, b)
    stops = _active_stops(conn, b)
    towns = conn.execute(
        "select name from public.route_template_stops where route_template_id = %s "
        "and kind = 'pass_through' order by chainage_m",
        (j["route_template_id"],),
    ).fetchall()
    return ToolResult(
        {
            "passenger_stops": [s["name"] for s in stops],
            "places_passed_without_stopping": [t[0] for t in towns],
            "note": "Only passenger stops have arrival times. Other places on the road are not stops.",
        }
    )


def get_remaining_stops(conn, b: Binding) -> ToolResult:
    stops = [s for s in _active_stops(conn, b) if s["status"] != "departed"]
    eta = _eta(conn, b)
    by_name = {s["name"]: s for s in (eta["stops"] if eta else [])}
    return ToolResult(
        {
            "count": len(stops),
            "stops": [
                {
                    "name": s["name"],
                    "expected_arrival": (by_name.get(s["name"]) or {}).get("eta"),
                    "currently_at_this_stop": s["status"] == "arrived",
                }
                for s in stops
            ],
        },
        availability=_availability(eta),
    )


def get_next_stop_after(conn, b: Binding, stop_name: str = "") -> ToolResult:
    stops = _active_stops(conn, b)
    found = _find_stop(stops, stop_name)
    if found is None:
        return ToolResult(
            {"stop_name": stop_name},
            availability="not_on_route",
            note=f"{stop_name} is not a passenger stop on this journey.",
        )
    later = [s for s in stops if s["sequence"] > found["sequence"]]
    j = _journey(conn, b)
    return ToolResult(
        {"after": found["name"], "next_stop": later[0]["name"] if later else j["destination_name"]}
    )


def get_stop_status(conn, b: Binding, stop_name: str = "") -> ToolResult:
    found = _find_stop(_active_stops(conn, b), stop_name)
    if found is None:
        return ToolResult(
            {"stop_name": stop_name},
            availability="not_on_route",
            note=f"{stop_name} is not a passenger stop on this journey.",
        )
    return ToolResult(
        {
            "stop": found["name"],
            "recorded_status": found["status"],  # pending | arrived | departed
            "arrived_at": found["arrived_at"].isoformat() if found["arrived_at"] else None,
            "departed_at": found["departed_at"].isoformat() if found["departed_at"] else None,
            "note": "Status comes from events recorded by the operator, not from the bus position.",
        }
    )


def get_stop_history(conn, b: Binding) -> ToolResult:
    done = [s for s in _active_stops(conn, b) if s["status"] == "departed"]
    waits = [
        (s["departed_at"] - s["arrived_at"]).total_seconds() / 60
        for s in done
        if s["arrived_at"] and s["departed_at"]
    ]
    return ToolResult(
        {
            "completed_stops": [s["name"] for s in done],
            "completed_count": len(done),
            "total_waiting_minutes_at_stops": round(sum(waits), 1),
            "average_wait_minutes": round(sum(waits) / len(waits), 1) if waits else None,
        }
    )


def get_stop_passenger_counts(conn, b: Binding, stop_name: str = "") -> ToolResult:
    j = _journey(conn, b)
    if not j["public_counts_enabled"]:
        return ToolResult(
            {}, availability="not_public", note="Passenger counts are not shared for this journey."
        )
    found = _find_stop(_active_stops(conn, b), stop_name)
    if found is None:
        return ToolResult({"stop_name": stop_name}, availability="not_on_route")
    return ToolResult(
        {
            "stop": found["name"],
            "planned_boarding": found["pickup_count"],
            "planned_alighting": found["drop_count"],
            "note": "Planned figures from confirmed bookings.",
        }
    )


def get_onboard_passenger_count(conn, b: Binding) -> ToolResult:
    j = _journey(conn, b)
    if not j["public_counts_enabled"]:
        return ToolResult(
            {}, availability="not_public", note="Passenger counts are not shared for this journey."
        )
    summary = stop_events.onboard(conn, b.ctx, b.journey_id)
    if summary["method"] == "recorded_events":
        return ToolResult(
            {"onboard": summary["onboard"], "method": "recorded boardings and alightings"}
        )
    return ToolResult(
        {"planned_onboard": summary["planned_onboard"], "method": "planned only"},
        note="No boardings have been recorded yet, so only the planned figure is known.",
    )


def get_journey_progress(conn, b: Binding) -> ToolResult:
    eta = _eta(conn, b)
    j = _journey(conn, b)
    if eta is None:
        return ToolResult({}, availability="unknown", note="No route has been assigned yet.")
    elapsed_min = max((datetime.now(UTC) - j["departure_at"]).total_seconds() / 60, 0)
    travelled_km = eta["travelled_distance_m"] / 1000
    waits = get_stop_history(conn, b).data["total_waiting_minutes_at_stops"]
    driving_min = max(elapsed_min - waits, 0)
    speed = (
        round(travelled_km / (driving_min / 60), 1)
        if driving_min >= 5 and travelled_km > 1
        else None
    )
    return ToolResult(
        {
            "travelled_km": round(travelled_km, 1),
            "remaining_km": round(eta["remaining_distance_m"] / 1000, 1),
            "progress_percent": round(eta["progress_pct"]),
            "past_halfway": eta["progress_pct"] >= 50,
            "elapsed_minutes": round(elapsed_min)
            if j["status"] in ("in_progress", "disrupted", "completed")
            else 0,
            "average_speed_kmh_while_driving": speed,
            "position_age_seconds": eta["gps_age_s"],
        },
        availability=_availability(eta),
        note="Average speed is only given once enough driving time has been recorded."
        if speed is None
        else None,
    )


def get_journey_delay(conn, b: Binding) -> ToolResult:
    eta = _eta(conn, b)
    if eta is None or not eta.get("commitment"):
        return ToolResult({}, availability="unknown")
    c = eta["commitment"]
    return ToolResult(
        {
            "arrival_promised_at_booking": c["original_eta"],
            "arrival_now_expected": c["predicted_eta"],
            "minutes_behind_promise": round(c["delay_minutes"]),
            "status": c["status"],
            "is_early": c["is_early"],
        },
        availability=_availability(eta),
    )


def get_traffic_summary(conn, b: Binding) -> ToolResult:
    eta = _eta(conn, b)
    alerts = conn.execute(
        "select type, message from public.journey_alerts where journey_id = %s and is_public "
        "and resolved_at is null and type in ('traffic', 'road_closure', 'delay') order by created_at",
        (b.journey_id,),
    ).fetchall()
    return ToolResult(
        {
            "slow_traffic_ahead": bool(eta and eta["flags"].get("traffic_ahead")),
            "road_closure_ahead": bool(eta and eta["flags"].get("closure_ahead")),
            "alerts": [{"type": t, "message": m} for t, m in alerts],
            "source": "simulated traffic data (this system has no live traffic feed)",
        },
        availability=_availability(eta),
    )


def compare_remaining_routes(conn, b: Binding) -> ToolResult:
    """Explain the latest route evaluation. This never changes the route."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            "select decided_at, outcome, reason, chosen_name, saving_minutes, details "
            "from public.route_decisions where journey_id = %s order by decided_at desc limit 1",
            (b.journey_id,),
        ).fetchone()
    if row is None:
        return ToolResult(
            {"evaluated": False},
            note="No alternative routes have been compared for this journey. The current route is being followed.",
        )
    return ToolResult(
        {
            "evaluated": True,
            "evaluated_at": row["decided_at"].isoformat(),
            "outcome": row["outcome"],
            "reason": row["reason"],
            "alternative_considered": row["chosen_name"],
            "minutes_saved_by_alternative": round(row["saving_minutes"] or 0),
            "note": "This is an explanation of a past comparison. Route decisions are made by the operator's system, not by this assistant.",
        }
    )


# ------------------------------------------------------------------ registry

Tool = Callable[..., ToolResult]
STOP_ARG = {
    "type": "object",
    "properties": {"stop_name": {"type": "string", "description": "Name of a passenger stop"}},
    "required": ["stop_name"],
}
NO_ARGS = {"type": "object", "properties": {}}

REGISTRY: dict[str, tuple[Tool, ToolSpec]] = {
    "get_journey_overview": (
        get_journey_overview,
        ToolSpec(
            "get_journey_overview",
            "Origin, destination, status, departure time and the arrival time promised at booking.",
            NO_ARGS,
        ),
    ),
    "get_route_summary": (
        get_route_summary,
        ToolSpec(
            "get_route_summary",
            "Which route option the bus follows, the passenger stops in order, and whether the route changed during the journey.",
            NO_ARGS,
        ),
    ),
    "get_route_geography": (
        get_route_geography,
        ToolSpec(
            "get_route_geography",
            "Passenger stops versus places the bus passes without stopping. Use to answer whether the bus passes or stops at a town.",
            NO_ARGS,
        ),
    ),
    "get_remaining_stops": (
        get_remaining_stops,
        ToolSpec(
            "get_remaining_stops",
            "The passenger stops still to be served, in order, with expected arrival times.",
            NO_ARGS,
        ),
    ),
    "get_next_stop_after": (
        get_next_stop_after,
        ToolSpec(
            "get_next_stop_after", "The passenger stop that comes after a given stop.", STOP_ARG
        ),
    ),
    "get_stop_status": (
        get_stop_status,
        ToolSpec(
            "get_stop_status",
            "Whether the bus has been recorded as arrived at or departed from a stop.",
            STOP_ARG,
        ),
    ),
    "get_stop_history": (
        get_stop_history,
        ToolSpec(
            "get_stop_history", "Stops completed so far and time spent waiting at them.", NO_ARGS
        ),
    ),
    "get_stop_passenger_counts": (
        get_stop_passenger_counts,
        ToolSpec(
            "get_stop_passenger_counts",
            "Planned number of passengers boarding and alighting at a stop, if the operator shares counts.",
            STOP_ARG,
        ),
    ),
    "get_onboard_passenger_count": (
        get_onboard_passenger_count,
        ToolSpec(
            "get_onboard_passenger_count",
            "Passengers currently on board, if the operator shares counts.",
            NO_ARGS,
        ),
    ),
    "get_journey_progress": (
        get_journey_progress,
        ToolSpec(
            "get_journey_progress",
            "Distance travelled and remaining, progress percent, elapsed time and average speed.",
            NO_ARGS,
        ),
    ),
    "get_journey_delay": (
        get_journey_delay,
        ToolSpec(
            "get_journey_delay",
            "How the expected arrival compares with the arrival promised at booking.",
            NO_ARGS,
        ),
    ),
    "get_traffic_summary": (
        get_traffic_summary,
        ToolSpec(
            "get_traffic_summary",
            "Slow traffic, closures and delay alerts on the remaining route.",
            NO_ARGS,
        ),
    ),
    "compare_remaining_routes": (
        compare_remaining_routes,
        ToolSpec(
            "compare_remaining_routes",
            "Explain the latest comparison of the current route with alternatives. Explanation only; never changes the route.",
            NO_ARGS,
        ),
    ),
}

STRING_ARGS = {"stop_name"}
MAX_ARG_LENGTH = 120


class UnknownTool(Exception):
    pass


def specs() -> list[ToolSpec]:
    return [spec for _, spec in REGISTRY.values()]


def run_tool(conn: psycopg.Connection, binding: Binding, name: str, arguments: dict) -> dict:
    """Validate arguments and run one tool for the bound journey. Unknown tools are refused."""
    if name not in REGISTRY:
        raise UnknownTool(name)
    func, spec = REGISTRY[name]
    allowed = set(spec.parameters.get("properties", {}))
    clean = {}
    for key, value in (arguments or {}).items():
        if key not in allowed:
            continue  # anything else (for example a journey id) is ignored
        if key in STRING_ARGS:
            clean[key] = str(value)[:MAX_ARG_LENGTH]
    for required in spec.parameters.get("required", []):
        if not clean.get(required):
            return ToolResult({}, availability="unknown", note=f"{required} is required").to_dict()
    return func(conn, binding, **clean).to_dict()
