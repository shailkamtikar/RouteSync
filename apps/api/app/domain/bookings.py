"""Bookings. A booking is always created under one journey and never moves to another."""

import csv
import io
import secrets
import uuid

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row
from pydantic import ValidationError

from app.auth.deps import OperatorContext
from app.domain import journeys
from app.domain.audit import record_event
from app.domain.errors import Conflict, Invalid, NotFound
from app.schemas.journeys import BookingCreate, BookingUpdate

BOOKING_COLUMNS = (
    "id, journey_id, reference, contact_name, passenger_count, pickup_stop_name, "
    "drop_stop_name, pickup_stop_id, drop_stop_id, status, created_at, updated_at"
)
CSV_COLUMNS = ["reference", "contact_name", "passenger_count", "pickup_stop", "drop_stop"]
CSV_MAX_ROWS = 500
CSV_MAX_BYTES = 200_000
# A cell starting with one of these is treated as a formula by spreadsheet programs.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _attach_passengers(conn: psycopg.Connection, rows: list[dict]) -> list[dict]:
    if not rows:
        return rows
    by_booking: dict[uuid.UUID, list] = {row["id"]: [] for row in rows}
    with conn.cursor(row_factory=dict_row) as cur:
        for passenger in cur.execute(
            "select id, booking_id, name, seat_number, phone from public.booking_passengers "
            "where booking_id = any(%s) order by created_at, name",
            (list(by_booking),),
        ):
            by_booking[passenger.pop("booking_id")].append(passenger)
    for row in rows:
        row["passengers"] = by_booking[row["id"]]
    return rows


def list_bookings(conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID) -> list:
    journeys.get_journey(conn, ctx, journey_id)
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            f"select {BOOKING_COLUMNS} from public.bookings "
            "where journey_id = %s and operator_id = %s order by created_at, reference",
            (journey_id, ctx.operator_id),
        ).fetchall()
    return _attach_passengers(conn, rows)


def get_booking(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID, booking_id: uuid.UUID
) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            f"select {BOOKING_COLUMNS} from public.bookings "
            "where id = %s and journey_id = %s and operator_id = %s",
            (booking_id, journey_id, ctx.operator_id),
        ).fetchone()
    if row is None:
        raise NotFound("Booking not found")
    return _attach_passengers(conn, [row])[0]


def _editable_journey(conn, ctx: OperatorContext, journey_id: uuid.UUID) -> dict:
    journey = journeys.get_journey(conn, ctx, journey_id, lock=True)
    if journey["status"] not in journeys.PRE_DEPARTURE_STATUSES:
        raise Conflict("Bookings cannot change after the journey has departed or ended")
    return journey


def _after_booking_change(conn, ctx: OperatorContext, journey_id: uuid.UUID) -> bool:
    """Flag the stop plan for review if stops were already confirmed. Returns capacity warning."""
    conn.execute(
        "update public.journeys set plan_needs_review = true where id = %s and operator_id = %s "
        "and not plan_needs_review "
        "and exists (select 1 from public.journey_stops where journey_id = %s)",
        (journey_id, ctx.operator_id, journey_id),
    )
    journey = journeys.get_journey(conn, ctx, journey_id)
    return journey["booked_passengers"] > journey["bus_capacity"]


def _insert_booking(conn, ctx: OperatorContext, journey: dict, data: BookingCreate) -> uuid.UUID:
    if data.passenger_count > journey["bus_capacity"]:
        raise Invalid(
            f"passenger_count {data.passenger_count} exceeds the bus capacity "
            f"of {journey['bus_capacity']}"
        )
    reference = data.reference or f"RS-{secrets.token_hex(4).upper()}"
    try:
        with conn.transaction():
            booking_id = conn.execute(
                "insert into public.bookings (operator_id, journey_id, reference, contact_name, "
                "passenger_count, pickup_stop_name, drop_stop_name) "
                "values (%s, %s, %s, %s, %s, %s, %s) returning id",
                (
                    ctx.operator_id,
                    journey["id"],
                    reference,
                    data.contact_name,
                    data.passenger_count,
                    data.pickup_stop_name,
                    data.drop_stop_name,
                ),
            ).fetchone()[0]
    except pg_errors.UniqueViolation:
        raise Conflict(f"Booking reference {reference} already exists on this journey") from None
    for passenger in data.passengers:
        conn.execute(
            "insert into public.booking_passengers (operator_id, journey_id, booking_id, name, "
            "seat_number, phone) values (%s, %s, %s, %s, %s, %s)",
            (
                ctx.operator_id,
                journey["id"],
                booking_id,
                passenger.name,
                passenger.seat_number,
                passenger.phone,
            ),
        )
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        journey_id=journey["id"],
        event_type="booking_created",
        entity_type="booking",
        entity_id=booking_id,
        payload={"passenger_count": data.passenger_count},
    )
    return booking_id


def create_booking(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID, data: BookingCreate
) -> tuple[dict, bool]:
    journey = _editable_journey(conn, ctx, journey_id)
    booking_id = _insert_booking(conn, ctx, journey, data)
    warning = _after_booking_change(conn, ctx, journey_id)
    return get_booking(conn, ctx, journey_id, booking_id), warning


def update_booking(
    conn: psycopg.Connection,
    ctx: OperatorContext,
    journey_id: uuid.UUID,
    booking_id: uuid.UUID,
    data: BookingUpdate,
) -> tuple[dict, bool]:
    journey = _editable_journey(conn, ctx, journey_id)
    current = get_booking(conn, ctx, journey_id, booking_id)
    if current["status"] != "confirmed":
        raise Conflict("A cancelled booking cannot be edited")
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not changes:
        return current, False
    merged = {**current, **changes}
    if merged["pickup_stop_name"].lower() == merged["drop_stop_name"].lower():
        raise Invalid("pickup and drop stops must be different")
    if merged["passenger_count"] > journey["bus_capacity"]:
        raise Invalid("passenger_count exceeds the bus capacity")
    if merged["passenger_count"] < len(current["passengers"]):
        raise Invalid("passenger_count is lower than the number of passenger details recorded")
    # A changed stop name must be matched to a stop again.
    for kind in ("pickup", "drop"):
        if f"{kind}_stop_name" in changes:
            changes[f"{kind}_stop_id"] = None
    assignments = ", ".join(f"{column} = %s" for column in changes)
    conn.execute(
        f"update public.bookings set {assignments} "
        "where id = %s and journey_id = %s and operator_id = %s",
        (*changes.values(), booking_id, journey_id, ctx.operator_id),
    )
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        journey_id=journey_id,
        event_type="booking_updated",
        entity_type="booking",
        entity_id=booking_id,
        payload={"fields": sorted(changes)},
    )
    warning = _after_booking_change(conn, ctx, journey_id)
    return get_booking(conn, ctx, journey_id, booking_id), warning


def cancel_booking(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID, booking_id: uuid.UUID
) -> dict:
    _editable_journey(conn, ctx, journey_id)
    current = get_booking(conn, ctx, journey_id, booking_id)
    if current["status"] == "cancelled":
        return current
    conn.execute(
        "update public.bookings set status = 'cancelled' "
        "where id = %s and journey_id = %s and operator_id = %s",
        (booking_id, journey_id, ctx.operator_id),
    )
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        journey_id=journey_id,
        event_type="booking_cancelled",
        entity_type="booking",
        entity_id=booking_id,
    )
    _after_booking_change(conn, ctx, journey_id)
    return get_booking(conn, ctx, journey_id, booking_id)


# ------------------------------------------------------------------ CSV import


def parse_bookings_csv(raw: bytes) -> list[BookingCreate]:
    """Parse and validate the whole file. Raises Invalid listing every bad row."""
    if len(raw) > CSV_MAX_BYTES:
        raise Invalid("The file is too large (limit 200 KB)")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Invalid("The file must be UTF-8 text") from None
    reader = csv.DictReader(io.StringIO(text))
    header = [name.strip().lower() for name in (reader.fieldnames or [])]
    if header != CSV_COLUMNS:
        raise Invalid(f"The header row must be exactly: {','.join(CSV_COLUMNS)}")
    reader.fieldnames = header

    bookings: list[BookingCreate] = []
    problems: list[dict] = []
    seen_references: set[str] = set()
    for line, row in enumerate(reader, start=2):
        if len(bookings) + len(problems) >= CSV_MAX_ROWS:
            raise Invalid(f"The file has more than {CSV_MAX_ROWS} rows")
        cells = {key: (value or "").strip() for key, value in row.items() if key is not None}
        if None in row:
            problems.append({"line": line, "error": "too many columns"})
            continue
        if not any(cells.values()):
            continue
        formula = next((k for k, v in cells.items() if v.startswith(FORMULA_PREFIXES)), None)
        if formula:
            problems.append(
                {"line": line, "error": f"{formula} starts with a character that is not allowed"}
            )
            continue
        try:
            booking = BookingCreate(
                reference=cells["reference"] or None,
                contact_name=cells["contact_name"] or None,
                passenger_count=cells["passenger_count"],
                pickup_stop_name=cells["pickup_stop"],
                drop_stop_name=cells["drop_stop"],
            )
        except ValidationError as exc:
            first = exc.errors()[0]
            field = first["loc"][0] if first["loc"] else "row"
            problems.append({"line": line, "error": f"{field}: {first['msg']}"})
            continue
        if booking.reference:
            if booking.reference.lower() in seen_references:
                problems.append({"line": line, "error": "duplicate reference in file"})
                continue
            seen_references.add(booking.reference.lower())
        bookings.append(booking)

    if problems:
        raise Invalid("The file has invalid rows. Nothing was imported.", details=problems)
    if not bookings:
        raise Invalid("The file has no booking rows")
    return bookings


def import_bookings(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID, raw: bytes
) -> tuple[int, bool]:
    """All-or-nothing import: any failure rolls back every row of the file."""
    parsed = parse_bookings_csv(raw)
    journey = _editable_journey(conn, ctx, journey_id)
    with conn.transaction():
        for index, booking in enumerate(parsed, start=2):
            try:
                _insert_booking(conn, ctx, journey, booking)
            except (Conflict, Invalid) as exc:
                raise Invalid(
                    "The file has invalid rows. Nothing was imported.",
                    details=[{"line": index, "error": exc.message}],
                ) from None
    return len(parsed), _after_booking_change(conn, ctx, journey_id)
