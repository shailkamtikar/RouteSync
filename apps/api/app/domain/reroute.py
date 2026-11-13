"""Reroute evaluation for a running journey.

Flow: lock the journey -> build its state -> (only if something is wrong on the current route)
ask for whole-journey alternatives -> reject anything that breaks a hard constraint -> score ->
decide with guardrails -> record the decision -> apply, recommend, or keep.

A provider call is made only when there is a disruption on the remaining route. A journey
running normally costs no routing quota.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.auth.deps import OperatorContext
from app.config import get_settings
from app.domain import journeys, lifecycle, route_versions, routes
from app.domain import traffic as traffic_domain
from app.domain.audit import record_event
from app.domain.errors import Conflict, Invalid
from app.eta import commitment as cm
from app.eta.traffic import traffic_on_route
from app.optimizer import geo
from app.optimizer.candidates import generate_candidates, remaining_current_route
from app.optimizer.constraints import is_feasible
from app.optimizer.decision import Decision, DecisionContext, decide
from app.optimizer.models import ActiveStop, Candidate, CorridorVariant, JourneyState, Tolerances
from app.optimizer.scoring import ScoreContext, Scored, rank, score_candidate
from app.providers.routing.base import RoutingProvider

logger = logging.getLogger(__name__)
RUNNING_STATUSES = ("in_progress", "disrupted")
UNRECORDED_STOP_MARGIN_M = 2000.0
SYSTEM_ROLE = "owner"  # the engine acts with the operator's own authority, inside the rules


def _lock(conn: psycopg.Connection, journey_id: uuid.UUID) -> bool:
    """One evaluation per journey at a time. Returns False if another one is running."""
    return conn.execute(
        "select pg_try_advisory_xact_lock(hashtextextended(%s, 0))", (f"reroute:{journey_id}",)
    ).fetchone()[0]


def _load(conn: psycopg.Connection, operator_id: uuid.UUID, journey_id: uuid.UUID) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            select j.id, j.operator_id, j.status, j.manual_mode, j.route_template_id,
                   j.booking_eta_at, j.last_position_at, j.last_reroute_eval_at,
                   j.reroute_pending_name, j.reroute_pending_count, j.current_route_version_id,
                   extensions.st_x(j.last_position::extensions.geometry) as lng,
                   extensions.st_y(j.last_position::extensions.geometry) as lat,
                   v.distance_m, v.duration_s, v.version,
                   extensions.st_asgeojson(v.geometry::extensions.geometry)::jsonb -> 'coordinates'
                     as route,
                   extensions.st_asgeojson(t.geometry::extensions.geometry)::jsonb -> 'coordinates'
                     as corridor,
                   t.variants, t.profile, s.destination_name
            from public.journeys j
            join public.services s on s.id = j.service_id
            left join public.route_versions v on v.id = j.current_route_version_id
            left join public.route_templates t on t.id = j.route_template_id
            where j.id = %s and j.operator_id = %s
            for update of j
            """,
            (journey_id, operator_id),
        ).fetchone()


def _remaining_stops(conn, journey_id: uuid.UUID) -> list[ActiveStop]:
    rows = conn.execute(
        "select s.id::text, s.name, extensions.st_x(s.location::extensions.geometry), "
        "       extensions.st_y(s.location::extensions.geometry), js.dwell_minutes "
        "from public.journey_stops js "
        "join public.route_template_stops s on s.id = js.route_template_stop_id "
        "where js.journey_id = %s and js.status <> 'departed' and s.role <> 'destination' "
        "order by js.sequence",
        (journey_id,),
    ).fetchall()
    return [ActiveStop(*row) for row in rows]


def _variants(raw: list, waypoints: list, corridor: list) -> tuple[CorridorVariant, ...]:
    """Approved detours of the route option, placed between the right pair of waypoints."""
    chainages = [geo.chainage_m(corridor, point) for point in waypoints]
    variants = []
    for item in raw or []:
        points = tuple((p["lng"], p["lat"]) for p in item.get("points", []))
        if not points:
            continue
        at = geo.chainage_m(corridor, points[0])
        if at <= chainages[0]:  # the detour is already behind the bus
            continue
        index = next((i for i, c in enumerate(chainages) if c > at), len(waypoints) - 1)
        variants.append(CorridorVariant(item.get("name", "Variant"), points, max(index, 1)))
    return tuple(variants)


def _traffic_delay_s(candidate: Candidate, incidents: list, now: datetime) -> tuple[float, bool]:
    """Extra seconds from slowdowns on this candidate, and whether a closure lies on it."""
    line = list(candidate.coordinates)
    on_route = traffic_on_route(line, incidents, now)
    length = geo.line_length_m(line)
    if length <= 0 or candidate.duration_s <= 0:
        return 0.0, bool(on_route.closures)
    seconds_per_m = candidate.duration_s / length
    cuts = sorted({0.0, length, *(e for s in on_route.segments for e in (s.from_m, s.to_m))})
    extra = 0.0
    for left, right in zip(cuts, cuts[1:], strict=False):
        middle = (left + right) / 2
        factor = max(
            (s.multiplier for s in on_route.segments if s.from_m <= middle <= s.to_m), default=1.0
        )
        extra += (right - left) * seconds_per_m * (factor - 1.0)
    return extra, bool(on_route.closures)


def _scored_payload(scored: Scored | None) -> dict | None:
    if scored is None:
        return None
    return {
        "name": scored.candidate.name,
        "source": scored.candidate.source,
        "distance_km": round(scored.candidate.distance_m / 1000, 1),
        "predicted_arrival": scored.predicted_arrival.isoformat(),
        "score": round(scored.score, 2),
        "breakdown": {
            key: {k: round(v, 2) for k, v in part.items()} for key, part in scored.breakdown.items()
        },
        "cost_estimate": round(scored.cost.total, 2),
        "toll_unknown": scored.cost.toll_unknown,
    }


def _set_alert(conn, row: dict, alert_type: str, severity: str, message: str | None) -> None:
    """Replace the journey's open alert of this type (None just clears it). Operator-only."""
    conn.execute(
        "update public.journey_alerts set resolved_at = now() "
        "where journey_id = %s and type = %s and resolved_at is null",
        (row["id"], alert_type),
    )
    if message:
        conn.execute(
            "insert into public.journey_alerts (operator_id, journey_id, type, severity, message, "
            "is_public) values (%s, %s, %s, %s, %s, false)",
            (row["operator_id"], row["id"], alert_type, severity, message[:500]),
        )


def evaluate(
    conn: psycopg.Connection,
    operator_id: uuid.UUID,
    journey_id: uuid.UUID,
    provider: RoutingProvider,
    *,
    trigger: str = "position",
    force: bool = False,
    apply_recommendation: bool = False,
    actor_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Evaluate one journey. Returns the decision, or None when nothing was evaluated
    (another evaluation is running, it is too soon, or the journey is not running)."""
    if not _lock(conn, journey_id):
        return None
    row = _load(conn, operator_id, journey_id)
    settings = get_settings()
    clock = now or datetime.now(UTC)
    if row is None or row["status"] not in RUNNING_STATUSES:
        return None
    if row["route"] is None or row["corridor"] is None or row["lng"] is None:
        return None
    last = row["last_reroute_eval_at"]
    if (
        not force
        and last is not None
        and clock - last < timedelta(seconds=settings.reroute_eval_interval_s)
    ):
        return None
    conn.execute(
        "update public.journeys set last_reroute_eval_at = %s where id = %s", (clock, journey_id)
    )

    route = tuple((c[0], c[1]) for c in row["route"])
    corridor = [(c[0], c[1]) for c in row["corridor"]]
    position = (row["lng"], row["lat"])
    stops = _remaining_stops(conn, journey_id)
    tolerances = Tolerances(corridor_m=float(settings.corridor_width_m))
    base_state = JourneyState(
        position=position,
        remaining_stops=tuple(stops),
        destination=corridor[-1],
        destination_name=row["destination_name"],
        corridor_centreline=tuple(corridor),
        current_route=route,
        current_route_distance_m=float(row["distance_m"]),
        current_route_duration_s=float(row["duration_s"]),
        profile=row["profile"] or "driving-car",
    )
    state = JourneyState(
        **{
            **base_state.__dict__,
            "variants": _variants(row["variants"], base_state.waypoints(), corridor),
        }
    )

    # A stop the bus has already passed with no recorded event is a recording problem, not a
    # routing problem: never "fix" it by rerouting, and never treat the stop as dropped.
    here = geo.chainage_m(list(route), position)
    behind = [
        stop.name
        for stop in stops
        if geo.chainage_m(list(route), stop.point) < here - UNRECORDED_STOP_MARGIN_M
    ]
    if behind:
        _set_alert(
            conn,
            row,
            "stop_events_missing",
            "warning",
            f"The bus is past {', '.join(behind)} but no arrival or departure was recorded.",
        )
        return {"action": "keep", "reason_code": "stops_unrecorded", "logged": False}
    _set_alert(conn, row, "stop_events_missing", "warning", None)

    incidents = traffic_domain.incidents_for_template(conn, operator_id, row["route_template_id"])
    traffic_now = traffic_domain.database_now(conn)
    current = remaining_current_route(state)
    current_delay, current_closed = _traffic_delay_s(current, incidents, traffic_now)
    current_feasible = is_feasible(current, state, tolerances)
    blocked = current_closed or not current_feasible

    # Nothing wrong ahead: keep the route and spend no routing quota.
    if not blocked and current_delay <= 0 and not (force and trigger == "operator"):
        if row["reroute_pending_name"] is not None:
            conn.execute(
                "update public.journeys set reroute_pending_name = null, reroute_pending_count = 0 "
                "where id = %s",
                (journey_id,),
            )
        return {"action": "keep", "reason_code": "no_disruption", "logged": False}

    generated = generate_candidates(provider, state, tolerances)
    delays: dict[str, float] = {}
    usable: list[Candidate] = []
    for candidate in generated.candidates:
        delay, closed = _traffic_delay_s(candidate, incidents, traffic_now)
        if closed:
            continue  # a closed road is never an option
        delays[candidate.name] = delay
        usable.append(candidate)

    config = settings.reroute_config()
    context = ScoreContext(
        now=clock,
        arrival_target=cm.planning_target(row["booking_eta_at"], settings.commitment_config()),
        dwell_s=sum(stop.dwell_minutes for stop in stops) * 60.0,
        extra_delay_s=delays,
    )
    ranked = rank(
        [
            score_candidate(c, context, settings.score_weights(), settings.cost_config())
            for c in usable
        ]
    )
    history = conn.execute(
        "select count(*), max(created_at) from public.route_versions "
        "where journey_id = %s and source in ('auto_reroute', 'operator_reroute')",
        (journey_id,),
    ).fetchone()
    gps_age = (clock - row["last_position_at"]).total_seconds() if row["last_position_at"] else None
    decision = decide(
        ranked,
        DecisionContext(
            now=clock,
            gps_fresh=gps_age is not None and gps_age <= settings.gps_stale_after_s,
            manual_mode=row["manual_mode"],
            reroutes_so_far=history[0],
            last_reroute_at=history[1],
            current_route_blocked=blocked,
            degraded=generated.degraded,
            pending_name=row["reroute_pending_name"],
            pending_count=row["reroute_pending_count"],
        ),
        config,
    )
    if decision.action == "recommend" and apply_recommendation:
        decision = Decision(
            "reroute",
            "operator_approved",
            decision.reason,
            chosen=decision.chosen,
            incumbent=decision.incumbent,
            saving_minutes=decision.saving_minutes,
            saving_pct=decision.saving_pct,
        )
    return _record(conn, row, decision, trigger, actor_id, generated.notes, clock)


def _record(
    conn, row: dict, decision: Decision, trigger: str, actor_id, notes: tuple, clock: datetime
) -> dict[str, Any]:
    journey_id, operator_id = row["id"], row["operator_id"]
    conn.execute(
        "update public.journeys set reroute_pending_name = %s, reroute_pending_count = %s "
        "where id = %s",
        (decision.pending_name, decision.pending_count, journey_id),
    )
    details = {
        "chosen": _scored_payload(decision.chosen),
        "current": _scored_payload(decision.incumbent),
        "saving_pct": round(decision.saving_pct, 1),
        "notes": list(notes),
        "traffic_simulated": True,
    }
    version_id = None
    system = OperatorContext(actor_id, None, operator_id, "", SYSTEM_ROLE)

    if decision.action == "reroute" and decision.chosen is not None:
        chosen = decision.chosen.candidate
        version = route_versions.create_version(
            conn,
            operator_id=operator_id,
            journey_id=journey_id,
            coordinates=list(chosen.coordinates),
            distance_m=chosen.distance_m,
            duration_s=chosen.duration_s,
            reason=decision.reason,
            source="operator_reroute" if trigger == "operator" else "auto_reroute",
            details={
                "previous_route_version_id": str(row["current_route_version_id"]),
                "previous_version": row["version"],
                "reason_code": decision.reason_code,
                **details,
            },
            created_by=actor_id,
        )
        version_id = version["id"]
        record_event(
            conn,
            operator_id=operator_id,
            actor_id=actor_id,
            journey_id=journey_id,
            event_type="route_rerouted",
            payload={
                "from_version": row["version"],
                "to_version": version["version"],
                "reason_code": decision.reason_code,
                "saving_minutes": round(decision.saving_minutes, 1),
                "automatic": trigger != "operator",
            },
        )
        _set_alert(conn, row, "reroute_recommended", "info", None)
        _set_alert(conn, row, "no_feasible_route", "critical", None)
        _set_alert(conn, row, "reroute", "info", f"Route changed: {decision.reason}")
        if row["status"] == "disrupted":
            lifecycle.apply_status(
                conn, system, journey_id, "disrupted", "in_progress", reason="rerouted"
            )
    elif decision.action == "recommend":
        _set_alert(
            conn, row, "reroute_recommended", "warning", f"Suggested change: {decision.reason}"
        )
    elif decision.action == "no_feasible_route":
        _set_alert(conn, row, "no_feasible_route", "critical", decision.reason)
        if row["status"] == "in_progress":
            lifecycle.apply_status(
                conn, system, journey_id, "in_progress", "disrupted", reason="no feasible route"
            )
    else:
        _set_alert(conn, row, "reroute_recommended", "info", None)

    decision_id = conn.execute(
        "insert into public.route_decisions (operator_id, journey_id, decided_at, outcome, "
        "reason_code, reason, chosen_name, saving_minutes, route_version_id, trigger, details) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
        (
            operator_id,
            journey_id,
            clock,
            decision.action,
            decision.reason_code,
            decision.reason,
            decision.chosen.candidate.name if decision.chosen else None,
            decision.saving_minutes,
            version_id,
            trigger,
            Jsonb(details),
        ),
    ).fetchone()[0]
    return {
        "id": decision_id,
        "action": decision.action,
        "reason_code": decision.reason_code,
        "reason": decision.reason,
        "chosen_name": decision.chosen.candidate.name if decision.chosen else None,
        "saving_minutes": round(decision.saving_minutes, 1),
        "route_version_id": version_id,
        "logged": True,
    }


def after_position_update(conn: psycopg.Connection, journey, provider: RoutingProvider) -> None:
    """Called after new positions were stored. A failure here never breaks position ingestion."""
    try:
        with conn.transaction():
            evaluate(conn, journey.operator_id, journey.journey_id, provider)
    except Exception:
        logger.exception("reroute evaluation failed")


# ------------------------------------------------------------------ operator actions


def operator_evaluate(
    conn, ctx: OperatorContext, journey_id: uuid.UUID, provider: RoutingProvider, apply: bool
) -> dict:
    journey = journeys.get_journey(conn, ctx, journey_id)
    if journey["status"] not in RUNNING_STATUSES:
        raise Conflict("The route can be re-evaluated only while the journey is running")
    result = evaluate(
        conn,
        ctx.operator_id,
        journey_id,
        provider,
        trigger="operator",
        force=True,
        apply_recommendation=apply,
        actor_id=ctx.user_id,
    )
    if result is None:
        raise Conflict("The journey has no position or route to evaluate yet")
    return result


def set_manual_mode(conn, ctx: OperatorContext, journey_id: uuid.UUID, enabled: bool) -> dict:
    journey = journeys.get_journey(conn, ctx, journey_id, lock=True)
    if journey["manual_mode"] != enabled:
        conn.execute(
            "update public.journeys set manual_mode = %s where id = %s and operator_id = %s",
            (enabled, journey_id, ctx.operator_id),
        )
        record_event(
            conn,
            operator_id=ctx.operator_id,
            actor_id=ctx.user_id,
            journey_id=journey_id,
            event_type="manual_mode_changed",
            payload={"enabled": enabled},
        )
    return journeys.get_journey(conn, ctx, journey_id)


def list_decisions(conn, ctx: OperatorContext, journey_id: uuid.UUID, limit: int = 50) -> list:
    journeys.get_journey(conn, ctx, journey_id)
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "select id, decided_at, outcome, reason_code, reason, chosen_name, saving_minutes, "
            "route_version_id, trigger, details from public.route_decisions "
            "where journey_id = %s and operator_id = %s order by decided_at desc, id desc limit %s",
            (journey_id, ctx.operator_id, limit),
        ).fetchall()


def set_variants(conn, ctx: OperatorContext, template_id: uuid.UUID, variants: list[dict]) -> dict:
    """Approve alternative roads for a route option. Each must lie inside its corridor."""
    template = routes.get_template(conn, ctx, template_id, lock=True)
    if template["status"] != "ready":
        raise Invalid("Generate the route for this option first")
    corridor = routes.full_coordinates(conn, template_id)
    width = get_settings().corridor_width_m
    for variant in variants:
        for point in variant["points"]:
            if geo.distance_to_line_m(corridor, (point["lng"], point["lat"])) > width:
                raise Invalid(
                    f"{variant['name']}: a point is more than {width / 1000:g} km from this route"
                )
    conn.execute(
        "update public.route_templates set variants = %s where id = %s and operator_id = %s",
        (Jsonb(variants), template_id, ctx.operator_id),
    )
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        event_type="route_variants_updated",
        entity_type="route_template",
        entity_id=template_id,
        payload={"variants": [v["name"] for v in variants]},
    )
    return {"variants": variants}
