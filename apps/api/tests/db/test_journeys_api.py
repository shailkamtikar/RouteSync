import uuid
from datetime import UTC, datetime

import pytest

from . import factories as f

pytestmark = pytest.mark.db

DEPART = "2031-03-01T16:30:00Z"
ARRIVE = "2031-03-02T02:00:00Z"
BOOKING = {"passenger_count": 2, "pickup_stop_name": "Pune", "drop_stop_name": "Nanded"}
CSV_HEADER = "reference,contact_name,passenger_count,pickup_stop,drop_stop\n"


@pytest.fixture
def setup(api, conn, tenants):
    """Bus and service for each operator, created directly in the database."""
    return {
        "bus1": str(f.make_bus(conn, tenants["op1"], capacity=40)),
        "service1": str(f.make_service(conn, tenants["op1"])),
        "bus2": str(f.make_bus(conn, tenants["op2"])),
        "service2": str(f.make_service(conn, tenants["op2"])),
    }


def new_journey(api, setup, who="owner1", **overrides):
    suffix = "1" if who != "owner2" else "2"
    body = {
        "bus_id": setup[f"bus{suffix}"],
        "service_id": setup[f"service{suffix}"],
        "departure_at": DEPART,
        "scheduled_arrival_at": ARRIVE,
        **overrides,
    }
    return api.post("/journeys", body, who=who)


def import_csv(api, journey_id, text, who="owner1"):
    return api.call(
        "POST",
        f"/journeys/{journey_id}/bookings/import",
        who,
        content=text.encode(),
        headers={**api.headers(who), "Content-Type": "text/csv"},
    )


# ------------------------------------------------------------------ journeys


def test_create_journey_is_a_draft_with_fixed_booking_eta(api, setup, conn):
    r = new_journey(api, setup)
    assert r.status_code == 201
    journey = r.json()
    assert journey["status"] == "draft"
    assert journey["booking_eta_at"] == journey["scheduled_arrival_at"]
    assert journey["timezone"] == "Asia/Kolkata"
    assert journey["origin_name"] == "Pune" and journey["destination_name"] == "Nanded"
    assert journey["booked_passengers"] == 0
    stored = conn.execute(
        "select extract(epoch from departure_at)::bigint from public.journeys where id = %s",
        (journey["id"],),
    ).fetchone()[0]
    assert stored == int(datetime(2031, 3, 1, 16, 30, tzinfo=UTC).timestamp())
    events = conn.execute(
        "select event_type from public.journey_events where journey_id = %s", (journey["id"],)
    ).fetchall()
    assert events == [("journey_created",)]


def test_overlapping_journey_for_same_bus_is_conflict(api, setup):
    assert new_journey(api, setup).status_code == 201
    r = new_journey(
        api, setup, departure_at="2031-03-01T20:00:00Z", scheduled_arrival_at="2031-03-02T05:00:00Z"
    )
    assert r.status_code == 409
    later = new_journey(
        api, setup, departure_at="2031-03-02T02:00:00Z", scheduled_arrival_at="2031-03-02T11:00:00Z"
    )
    assert later.status_code == 201


@pytest.mark.parametrize(
    "overrides",
    [
        {"scheduled_arrival_at": DEPART},
        {"scheduled_arrival_at": "2031-03-01T10:00:00Z"},
        {"scheduled_arrival_at": "2031-03-10T10:00:00Z"},
        {"departure_at": "2031-03-01T16:30:00"},
        {"departure_at": "tomorrow"},
        {"timezone": "Mars/Olympus"},
        {"bus_id": "nope"},
        {"status": "completed"},
        {"booking_eta_at": ARRIVE},
        {"operator_id": str(uuid.uuid4())},
    ],
)
def test_invalid_journey_is_rejected(api, setup, overrides):
    assert new_journey(api, setup, **overrides).status_code == 422
    assert api.get("/journeys").json() == []


def test_journey_cannot_use_another_operators_bus_or_service(api, setup):
    assert new_journey(api, setup, bus_id=setup["bus2"]).status_code == 404
    assert new_journey(api, setup, service_id=setup["service2"]).status_code == 404
    assert new_journey(api, setup, bus_id=str(uuid.uuid4())).status_code == 404


def test_archived_bus_cannot_be_scheduled(api, setup, conn):
    conn.execute("update public.buses set status = 'archived' where id = %s", (setup["bus1"],))
    assert new_journey(api, setup).status_code == 422


def test_cross_operator_journey_access_is_404(api, setup):
    theirs = new_journey(api, setup, who="owner2").json()["id"]
    assert api.get(f"/journeys/{theirs}").status_code == 404
    assert api.patch(f"/journeys/{theirs}", {"timezone": "UTC"}).status_code == 404
    assert api.get(f"/journeys/{theirs}/bookings").status_code == 404
    assert api.post(f"/journeys/{theirs}/bookings", BOOKING).status_code == 404
    assert import_csv(api, theirs, CSV_HEADER + "R1,,1,Pune,Nanded\n").status_code == 404
    assert api.get("/journeys").json() == []
    assert api.get(f"/journeys/{theirs}/bookings", who="owner2").json() == []


def test_unauthenticated_journey_calls_are_401(api, setup):
    journey_id = new_journey(api, setup).json()["id"]
    assert api.call("GET", "/journeys", who=None).status_code == 401
    assert (
        api.call("POST", f"/journeys/{journey_id}/bookings", who=None, json=BOOKING).status_code
        == 401
    )
    assert api.call("GET", f"/journeys/{journey_id}/bookings", who=None).status_code == 401


def test_two_journeys_of_same_service_are_independent(api, setup, conn, tenants):
    first = new_journey(api, setup).json()["id"]
    other_bus = str(f.make_bus(conn, tenants["op1"]))
    second = new_journey(api, setup, bus_id=other_bus).json()["id"]
    api.post(f"/journeys/{first}/bookings", BOOKING)
    assert len(api.get(f"/journeys/{first}/bookings").json()) == 1
    assert api.get(f"/journeys/{second}/bookings").json() == []
    assert api.get(f"/journeys/{second}").json()["booked_passengers"] == 0


def test_only_draft_journey_can_be_edited(api, setup, conn, tenants):
    journey_id = new_journey(api, setup).json()["id"]
    other_bus = str(f.make_bus(conn, tenants["op1"]))
    assert api.patch(f"/journeys/{journey_id}", {"bus_id": other_bus}).json()["bus_id"] == other_bus
    assert api.patch(f"/journeys/{journey_id}", {"bus_id": setup["bus2"]}).status_code == 404
    assert api.patch(f"/journeys/{journey_id}", {"departure_at": DEPART}).status_code == 422
    conn.execute("update public.journeys set status = 'ready' where id = %s", (journey_id,))
    assert api.patch(f"/journeys/{journey_id}", {"timezone": "UTC"}).status_code == 409


def test_list_filter_by_status(api, setup):
    new_journey(api, setup)
    assert len(api.get("/journeys?status=draft").json()) == 1
    assert api.get("/journeys?status=completed").json() == []
    assert api.get("/journeys?status=bogus").status_code == 422


# ------------------------------------------------------------------ bookings


@pytest.fixture
def journey_id(api, setup):
    return new_journey(api, setup).json()["id"]


def test_create_booking_with_passengers(api, journey_id):
    body = {
        **BOOKING,
        "reference": "REF-1",
        "contact_name": "Asha Kulkarni",
        "passengers": [
            {"name": "Asha Kulkarni", "seat_number": "12A", "phone": "+91 98000 00000"},
            {"name": "Ravi Kulkarni", "seat_number": "12B"},
        ],
    }
    r = api.post(f"/journeys/{journey_id}/bookings", body)
    assert r.status_code == 201
    result = r.json()
    assert result["capacity_warning"] is False
    assert result["booking"]["reference"] == "REF-1"
    assert result["booking"]["journey_id"] == journey_id
    assert [p["name"] for p in result["booking"]["passengers"]] == [
        "Asha Kulkarni",
        "Ravi Kulkarni",
    ]
    assert api.get(f"/journeys/{journey_id}").json()["booked_passengers"] == 2


def test_booking_reference_is_generated_and_unique_per_journey(api, journey_id):
    generated = api.post(f"/journeys/{journey_id}/bookings", BOOKING).json()["booking"]
    assert generated["reference"].startswith("RS-")
    assert (
        api.post(f"/journeys/{journey_id}/bookings", {**BOOKING, "reference": "X1"}).status_code
        == 201
    )
    assert (
        api.post(f"/journeys/{journey_id}/bookings", {**BOOKING, "reference": "X1"}).status_code
        == 409
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"passenger_count": 0},
        {"passenger_count": -3},
        {"passenger_count": 41},
        {"passenger_count": "two"},
        {"drop_stop_name": " PUNE "},
        {"pickup_stop_name": "   "},
        {"pickup_stop_name": "P" * 121},
        {"passengers": [{"name": "A"}, {"name": "B"}, {"name": "C"}]},
        {"passengers": [{"name": "A", "phone": "call me"}]},
        {"journey_id": str(uuid.uuid4())},
        {"status": "cancelled"},
    ],
)
def test_invalid_booking_is_rejected(api, journey_id, overrides):
    assert api.post(f"/journeys/{journey_id}/bookings", {**BOOKING, **overrides}).status_code == 422
    assert api.get(f"/journeys/{journey_id}/bookings").json() == []


def test_total_over_capacity_is_flagged_not_blocked(api, journey_id):
    first = api.post(f"/journeys/{journey_id}/bookings", {**BOOKING, "passenger_count": 30})
    assert first.json()["capacity_warning"] is False
    second = api.post(f"/journeys/{journey_id}/bookings", {**BOOKING, "passenger_count": 11})
    assert second.status_code == 201
    assert second.json()["capacity_warning"] is True


def test_booking_is_addressed_only_through_its_own_journey(api, setup, conn, tenants, journey_id):
    booking_id = api.post(f"/journeys/{journey_id}/bookings", BOOKING).json()["booking"]["id"]
    other_bus = str(f.make_bus(conn, tenants["op1"]))
    other_journey = new_journey(api, setup, bus_id=other_bus).json()["id"]
    assert api.get(f"/journeys/{other_journey}/bookings/{booking_id}").status_code == 404
    assert (
        api.patch(
            f"/journeys/{other_journey}/bookings/{booking_id}", {"passenger_count": 1}
        ).status_code
        == 404
    )
    assert api.delete(f"/journeys/{other_journey}/bookings/{booking_id}").status_code == 404
    assert api.get(f"/journeys/{journey_id}/bookings/{booking_id}").status_code == 200


def test_update_and_cancel_booking(api, journey_id):
    booking_id = api.post(f"/journeys/{journey_id}/bookings", BOOKING).json()["booking"]["id"]
    updated = api.patch(
        f"/journeys/{journey_id}/bookings/{booking_id}",
        {"passenger_count": 3, "drop_stop_name": "Beed"},
    )
    assert updated.status_code == 200
    assert updated.json()["booking"]["passenger_count"] == 3
    assert updated.json()["booking"]["drop_stop_name"] == "Beed"
    same = api.patch(f"/journeys/{journey_id}/bookings/{booking_id}", {"pickup_stop_name": "beed"})
    assert same.status_code == 422

    cancelled = api.delete(f"/journeys/{journey_id}/bookings/{booking_id}")
    assert cancelled.json()["status"] == "cancelled"
    assert api.get(f"/journeys/{journey_id}").json()["booked_passengers"] == 0
    assert (
        api.patch(
            f"/journeys/{journey_id}/bookings/{booking_id}", {"passenger_count": 1}
        ).status_code
        == 409
    )


def test_booking_change_after_stops_confirmed_flags_plan_for_review(api, conn, tenants, setup):
    template = f.make_template(conn, tenants["op1"], setup["service1"])
    stop = f.make_template_stop(conn, tenants["op1"], template, "Beed")
    journey_id = new_journey(api, setup).json()["id"]
    api.post(f"/journeys/{journey_id}/bookings", BOOKING)
    assert api.get(f"/journeys/{journey_id}").json()["plan_needs_review"] is False

    conn.execute(
        "update public.journeys set route_template_id = %s where id = %s", (template, journey_id)
    )
    f.make_journey_stop(conn, tenants["op1"], journey_id, template, stop)
    api.post(f"/journeys/{journey_id}/bookings", BOOKING)
    assert api.get(f"/journeys/{journey_id}").json()["plan_needs_review"] is True
    # The confirmed stop plan itself is not rewritten.
    assert (
        conn.execute(
            "select count(*) from public.journey_stops where journey_id = %s", (journey_id,)
        ).fetchone()[0]
        == 1
    )


def test_bookings_locked_after_departure(api, journey_id, conn):
    conn.execute("update public.journeys set status = 'in_progress' where id = %s", (journey_id,))
    assert api.post(f"/journeys/{journey_id}/bookings", BOOKING).status_code == 409


# ------------------------------------------------------------------ CSV import


def test_csv_import_creates_all_rows(api, journey_id):
    rows = "".join(f"C{i},Contact {i},1,Pune,Nanded\n" for i in range(10))
    r = import_csv(api, journey_id, CSV_HEADER + rows)
    assert r.status_code == 200
    assert r.json() == {"created": 10, "capacity_warning": False}
    assert len(api.get(f"/journeys/{journey_id}/bookings").json()) == 10


def test_csv_with_one_bad_row_imports_nothing(api, journey_id):
    rows = [f"C{i},,1,Pune,Nanded" for i in range(10)]
    rows[6] = "C6,,zero,Pune,Nanded"
    r = import_csv(api, journey_id, CSV_HEADER + "\n".join(rows) + "\n")
    assert r.status_code == 422
    assert r.json()["details"] == [
        {"line": 8, "error": r.json()["details"][0]["error"]},
    ]
    assert "passenger_count" in r.json()["details"][0]["error"]
    assert api.get(f"/journeys/{journey_id}/bookings").json() == []


@pytest.mark.parametrize("cell", ["=1+1", "+SUM(A1)", "-2+3", "@cmd", '=HYPERLINK("x")'])
def test_csv_formula_cells_are_rejected(api, journey_id, cell):
    r = import_csv(
        api, journey_id, CSV_HEADER + f'R1,"{cell.replace(chr(34), chr(34) * 2)}",1,Pune,Nanded\n'
    )
    assert r.status_code == 422
    assert "not allowed" in r.json()["details"][0]["error"]
    assert api.get(f"/journeys/{journey_id}/bookings").json() == []


def test_csv_duplicate_of_existing_reference_imports_nothing(api, journey_id):
    api.post(f"/journeys/{journey_id}/bookings", {**BOOKING, "reference": "DUP"})
    r = import_csv(api, journey_id, CSV_HEADER + "NEW,,1,Pune,Nanded\nDUP,,1,Pune,Nanded\n")
    assert r.status_code == 422
    assert r.json()["details"][0]["line"] == 3
    assert len(api.get(f"/journeys/{journey_id}/bookings").json()) == 1


@pytest.mark.parametrize(
    "text",
    [
        "",
        "reference,passenger_count\nR1,1\n",
        CSV_HEADER,
        CSV_HEADER + "R1,,1,Pune,Nanded,extra\n",
        CSV_HEADER + "R1,,1,Pune,Nanded\nR1,,1,Pune,Nanded\n",
        CSV_HEADER + "R1,,1,Pune,Pune\n",
        CSV_HEADER + "R1,,99,Pune,Nanded\n",
    ],
)
def test_malformed_csv_is_rejected(api, journey_id, text):
    assert import_csv(api, journey_id, text).status_code == 422
    assert api.get(f"/journeys/{journey_id}/bookings").json() == []


def test_csv_row_limit(api, journey_id):
    rows = "".join(f"C{i},,1,Pune,Nanded\n" for i in range(501))
    assert import_csv(api, journey_id, CSV_HEADER + rows).status_code == 422
    assert api.get(f"/journeys/{journey_id}/bookings").json() == []


def test_non_utf8_csv_is_rejected(api, journey_id):
    r = api.call(
        "POST",
        f"/journeys/{journey_id}/bookings/import",
        "owner1",
        content=b"\xff\xfe\x00bad",
        headers={**api.headers("owner1"), "Content-Type": "text/csv"},
    )
    assert r.status_code == 422


# ------------------------------------------------------------------ regression


def test_fleet_endpoints_still_work(api, setup):
    assert len(api.get("/buses").json()) == 1
    assert len(api.get("/services").json()) == 1
