"""Authorization matrix, generated from the API schema.

Every operator endpoint must answer 401 without a token, 403 for a user without membership,
and never 2xx for another operator's resources. New endpoints are covered automatically.
"""

import uuid

import pytest

from app.main import app

from .live_fixtures import build_live_journey

pytestmark = pytest.mark.db

PUBLIC_PREFIXES = ("/healthz", "/readyz", "/api/v1/public/", "/api/v1/ingest/")
# Endpoints a dispatcher may not call (owner only).
OWNER_ONLY = {
    ("DELETE", "/api/v1/buses/{bus_id}"),
    ("DELETE", "/api/v1/services/{service_id}"),
    ("DELETE", "/api/v1/route-templates/{template_id}"),
}
BODIES = {"POST": {}, "PUT": {}, "PATCH": {}}


def operator_endpoints():
    found = []
    for path, methods in app.openapi()["paths"].items():
        if path.startswith(PUBLIC_PREFIXES):
            continue
        for method in methods:
            found.append((method.upper(), path))
    return sorted(found)


ENDPOINTS = operator_endpoints()


def fill(path: str, ids: dict) -> str:
    out = path
    for key, value in ids.items():
        out = out.replace("{" + key + "}", str(value))
    return out


@pytest.fixture
def victim(api, conn, tenants):
    """Operator 1's resources, which operator 2 must never reach."""
    w = build_live_journey(conn, tenants)
    booking = conn.execute(
        "insert into public.bookings (operator_id, journey_id, reference, passenger_count, "
        "pickup_stop_name, drop_stop_name) values (%s, %s, 'R1', 1, 'Pune', 'Nanded') returning id",
        (w["op"], w["journey"]),
    ).fetchone()[0]
    incident = conn.execute(
        "insert into public.traffic_incidents (operator_id, route_template_id, kind, multiplier, "
        "from_point, to_point, from_km, to_km) values (%s, %s, 'slow', 2, "
        "'POINT(75 19)'::extensions.geography, 'POINT(76 19)'::extensions.geography, 1, 2) returning id",
        (w["op"], w["template"]),
    ).fetchone()[0]
    stop_id = conn.execute(
        "select id from public.route_template_stops where route_template_id = %s limit 1",
        (w["template"],),
    ).fetchone()[0]
    return {
        "bus_id": w["bus"],
        "service_id": w["service"],
        "template_id": w["template"],
        "journey_id": w["journey"],
        "booking_id": booking,
        "stop_id": stop_id,
        "incident_id": incident,
    }


def test_the_matrix_covers_every_operator_endpoint():
    assert len(ENDPOINTS) >= 45
    assert ("GET", "/api/v1/journeys/{journey_id}/monitor") in ENDPOINTS


@pytest.mark.parametrize(("method", "path"), ENDPOINTS, ids=[f"{m} {p}" for m, p in ENDPOINTS])
def test_no_token_is_401(api, victim, method, path):
    r = api.call(
        method, fill(path, victim).removeprefix("/api/v1"), who=None, json=BODIES.get(method)
    )
    assert r.status_code == 401, r.text


@pytest.mark.parametrize(("method", "path"), ENDPOINTS, ids=[f"{m} {p}" for m, p in ENDPOINTS])
def test_user_without_membership_is_403(api, victim, method, path):
    r = api.call(
        method, fill(path, victim).removeprefix("/api/v1"), who="outsider", json=BODIES.get(method)
    )
    assert r.status_code == 403, r.text


@pytest.mark.parametrize(
    ("method", "path"),
    [e for e in ENDPOINTS if "{" in e[1]],
    ids=[f"{m} {p}" for m, p in ENDPOINTS if "{" in p],
)
def test_another_operator_never_succeeds(api, victim, method, path):
    r = api.call(
        method, fill(path, victim).removeprefix("/api/v1"), who="owner2", json=BODIES.get(method)
    )
    assert r.status_code in (404, 422), (r.status_code, r.text)
    assert r.status_code != 422 or "detail" in r.json()


@pytest.mark.parametrize(
    ("method", "path"), sorted(OWNER_ONLY), ids=[f"{m} {p}" for m, p in sorted(OWNER_ONLY)]
)
def test_owner_only_endpoints_refuse_dispatchers(api, victim, method, path):
    r = api.call(method, fill(path, victim).removeprefix("/api/v1"), who="dispatcher1")
    assert r.status_code == 403


def test_random_ids_are_404_not_500(api, victim):
    random = {k: uuid.uuid4() for k in victim}
    for method, path in ENDPOINTS:
        if "{" not in path or method != "GET":
            continue
        r = api.call("GET", fill(path, random).removeprefix("/api/v1"))
        assert r.status_code in (404, 409, 422), (path, r.status_code)
        assert "Traceback" not in r.text
