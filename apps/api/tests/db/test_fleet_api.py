import uuid

import pytest

from . import factories as f

pytestmark = pytest.mark.db

BUS = {"registration": "mh12 ab 1234", "capacity": 40}
SERVICE = {
    "origin_name": "Pune",
    "destination_name": "Nanded",
    "origin_location": {"lat": 18.5204, "lng": 73.8567},
    "destination_location": {"lat": 19.1383, "lng": 77.321},
}


def audit_types(conn, entity_id):
    rows = conn.execute(
        "select event_type from public.journey_events where entity_id = %s order by id",
        (entity_id,),
    ).fetchall()
    return [row[0] for row in rows]


# ------------------------------------------------------------------ buses


def test_create_bus_and_list(api, conn, tenants):
    r = api.post("/buses", BUS)
    assert r.status_code == 201
    bus = r.json()
    assert bus["registration"] == "MH12 AB 1234"
    assert bus["status"] == "active"
    assert "operator_id" not in bus
    assert [b["id"] for b in api.get("/buses").json()] == [bus["id"]]
    assert audit_types(conn, bus["id"]) == ["bus_created"]


def test_dispatcher_can_create_bus(api):
    assert api.post("/buses", BUS, who="dispatcher1").status_code == 201


def test_duplicate_registration_is_conflict(api):
    assert api.post("/buses", BUS).status_code == 201
    r = api.post("/buses", {"registration": "MH12 AB 1234", "capacity": 30})
    assert r.status_code == 409
    assert r.json()["code"] == "conflict"
    assert len(api.get("/buses").json()) == 1


def test_other_operator_can_reuse_registration(api):
    assert api.post("/buses", BUS).status_code == 201
    assert api.post("/buses", BUS, who="owner2").status_code == 201


@pytest.mark.parametrize(
    "body",
    [
        {"registration": "MH12AB1234", "capacity": 0},
        {"registration": "MH12AB1234", "capacity": 101},
        {"registration": "MH12AB1234", "capacity": "many"},
        {"registration": "", "capacity": 40},
        {"registration": "ab", "capacity": 40},
        {"registration": "MH12;drop table", "capacity": 40},
        {"registration": "MH12AB1234"},
        {"registration": "MH12AB1234", "capacity": 40, "operator_id": str(uuid.uuid4())},
    ],
)
def test_invalid_bus_is_rejected(api, body):
    assert api.post("/buses", body).status_code == 422
    assert api.get("/buses").json() == []


def test_cross_operator_bus_access_is_404(api, conn):
    bus_id = api.post("/buses", BUS, who="owner2").json()["id"]
    assert api.get(f"/buses/{bus_id}").status_code == 404
    assert api.patch(f"/buses/{bus_id}", {"capacity": 10}).status_code == 404
    assert api.delete(f"/buses/{bus_id}").status_code == 404
    assert api.get("/buses").json() == []
    # Nothing changed for the real owner.
    theirs = api.get(f"/buses/{bus_id}", who="owner2").json()
    assert theirs["capacity"] == 40 and theirs["status"] == "active"


def test_unknown_and_malformed_bus_ids(api):
    assert api.get(f"/buses/{uuid.uuid4()}").status_code == 404
    assert api.get("/buses/not-a-uuid").status_code == 422


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/buses"), ("POST", "/buses"), ("GET", "/services"), ("POST", "/services")],
)
def test_unauthenticated_is_401(api, method, path):
    assert api.call(method, path, who=None, json=BUS).status_code == 401


def test_user_without_membership_is_403(api):
    assert api.get("/buses", who="outsider").status_code == 403


def test_update_bus(api, conn):
    bus = api.post("/buses", BUS).json()
    r = api.patch(f"/buses/{bus['id']}", {"capacity": 45})
    assert r.status_code == 200
    assert r.json()["capacity"] == 45
    assert r.json()["registration"] == "MH12 AB 1234"
    assert audit_types(conn, bus["id"]) == ["bus_created", "bus_updated"]


def test_update_bus_to_existing_registration_is_conflict(api):
    api.post("/buses", BUS)
    other = api.post("/buses", {"registration": "MH14 XY 9999", "capacity": 30}).json()
    r = api.patch(f"/buses/{other['id']}", {"registration": "MH12 AB 1234"})
    assert r.status_code == 409
    assert api.get(f"/buses/{other['id']}").json()["registration"] == "MH14 XY 9999"


def test_stale_update_is_conflict(api):
    bus = api.post("/buses", BUS).json()
    r = api.patch(
        f"/buses/{bus['id']}",
        {"capacity": 20, "expected_updated_at": "2000-01-01T00:00:00Z"},
    )
    assert r.status_code == 409
    fresh = api.patch(
        f"/buses/{bus['id']}", {"capacity": 20, "expected_updated_at": bus["updated_at"]}
    )
    assert fresh.status_code == 200


def test_only_owner_can_remove_bus(api):
    bus = api.post("/buses", BUS).json()
    assert api.delete(f"/buses/{bus['id']}", who="dispatcher1").status_code == 403
    assert api.get(f"/buses/{bus['id']}").status_code == 200


def test_unused_bus_is_deleted(api, conn):
    bus = api.post("/buses", BUS).json()
    r = api.delete(f"/buses/{bus['id']}")
    assert r.json() == {"result": "deleted"}
    assert api.get(f"/buses/{bus['id']}").status_code == 404
    assert audit_types(conn, bus["id"]) == ["bus_created", "bus_deleted"]


def test_bus_used_by_a_journey_is_archived_not_deleted(api, conn, tenants):
    bus = api.post("/buses", BUS).json()
    service = f.make_service(conn, tenants["op1"])
    f.make_journey(conn, tenants["op1"], bus["id"], service)
    assert api.delete(f"/buses/{bus['id']}").json() == {"result": "archived"}
    assert api.get(f"/buses/{bus['id']}").json()["status"] == "archived"
    assert api.get("/buses").json() == []
    assert len(api.get("/buses?include_archived=true").json()) == 1


# ------------------------------------------------------------------ services


def test_create_service_and_read_back(api, conn):
    r = api.post("/services", SERVICE)
    assert r.status_code == 201
    service = r.json()
    assert service["origin_name"] == "Pune"
    assert service["origin_location"] == pytest.approx({"lat": 18.5204, "lng": 73.8567})
    assert api.get(f"/services/{service['id']}").json() == service
    assert audit_types(conn, service["id"]) == ["service_created"]


def test_service_without_coordinates(api):
    r = api.post("/services", {"origin_name": "Pune", "destination_name": "Nanded"})
    assert r.status_code == 201
    assert r.json()["origin_location"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"origin_name": "Pune", "destination_name": " pune "},
        {"origin_name": "", "destination_name": "Nanded"},
        {"origin_name": "   ", "destination_name": "Nanded"},
        {"origin_name": "Pune"},
        {"origin_name": "P" * 121, "destination_name": "Nanded"},
        {**SERVICE, "origin_location": {"lat": 123, "lng": 73.8}},
        {**SERVICE, "destination_location": {"lat": 19.1, "lng": 181}},
    ],
)
def test_invalid_service_is_rejected(api, body):
    assert api.post("/services", body).status_code == 422
    assert api.get("/services").json() == []


def test_cross_operator_service_access_is_404(api):
    service_id = api.post("/services", SERVICE, who="owner2").json()["id"]
    assert api.get(f"/services/{service_id}").status_code == 404
    assert api.patch(f"/services/{service_id}", {"origin_name": "Mumbai"}).status_code == 404
    assert api.delete(f"/services/{service_id}").status_code == 404
    assert api.get(f"/services/{service_id}", who="owner2").json()["origin_name"] == "Pune"


def test_update_service_cannot_make_origin_equal_destination(api):
    service = api.post("/services", SERVICE).json()
    r = api.patch(f"/services/{service['id']}", {"destination_name": "PUNE"})
    assert r.status_code == 422
    assert api.get(f"/services/{service['id']}").json()["destination_name"] == "Nanded"


def test_update_service(api):
    service = api.post("/services", SERVICE).json()
    r = api.patch(
        f"/services/{service['id']}",
        {"destination_name": "Latur", "destination_location": {"lat": 18.4, "lng": 76.58}},
    )
    assert r.status_code == 200
    assert r.json()["destination_name"] == "Latur"
    assert r.json()["destination_location"] == pytest.approx({"lat": 18.4, "lng": 76.58})


def test_service_removal_deletes_or_archives(api, conn, tenants):
    unused = api.post("/services", SERVICE).json()
    assert api.delete(f"/services/{unused['id']}", who="dispatcher1").status_code == 403
    assert api.delete(f"/services/{unused['id']}").json() == {"result": "deleted"}

    used = api.post("/services", {"origin_name": "Pune", "destination_name": "Latur"}).json()
    f.make_template(conn, tenants["op1"], used["id"])
    assert api.delete(f"/services/{used['id']}").json() == {"result": "archived"}
    assert api.get(f"/services/{used['id']}").json()["status"] == "archived"


# ------------------------------------------------------------------ regression


def test_earlier_endpoints_still_work(api):
    assert api.client.get("/healthz").status_code == 200
    me = api.get("/me", who="dispatcher1").json()
    assert me["role"] == "dispatcher" and me["operator_name"] == "Test Operator One"
