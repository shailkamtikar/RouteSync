"""Compact, public-safe journey context given to the model with every conversation."""

import uuid
from typing import Any

import psycopg

from app.companion.tools import Binding, _active_stops, _eta, _journey


def build_context(conn: psycopg.Connection, binding: Binding) -> dict[str, Any]:
    j = _journey(conn, binding)
    stops = _active_stops(conn, binding)
    eta = _eta(conn, binding)
    remaining = [s["name"] for s in stops if s["status"] != "departed"]
    done = [s["name"] for s in stops if s["status"] == "departed"]
    context: dict[str, Any] = {
        "origin": j["origin_name"],
        "destination": j["destination_name"],
        "route_option": j["route_name"],
        "status": j["status"],
        "timezone": j["timezone"],
        "passenger_stops_in_order": [s["name"] for s in stops],
        "completed_stops": done,
        "remaining_stops": remaining,
        "next_stop": eta["next_stop"]["name"]
        if eta
        else (remaining[0] if remaining else j["destination_name"]),
        "arrival_promised_at_booking": j["booking_eta_at"].isoformat(),
        "passenger_counts_shared": j["public_counts_enabled"],
    }
    if eta:
        context["expected_arrival"] = eta["destination"]["eta"]
        context["position"] = (
            "not live (last position is old)"
            if eta["flags"].get("stale")
            else "no live position yet"
            if eta["flags"].get("plan_based")
            else "live"
        )
        context["progress_percent"] = round(eta["progress_pct"])
        if eta.get("commitment"):
            context["minutes_behind_promise"] = round(eta["commitment"]["delay_minutes"])
    else:
        context["position"] = "unknown"
    return context


def journey_id_of(binding: Binding) -> uuid.UUID:
    return binding.journey_id
