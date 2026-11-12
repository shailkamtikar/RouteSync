"""Request and response models for journeys and bookings."""

import uuid
from datetime import datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator

from app.schemas.fleet import StrictModel, _clean_text

MAX_JOURNEY_DURATION = timedelta(hours=72)
StopName = Annotated[str, Field(min_length=1, max_length=120)]


def _valid_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("unknown time zone") from None
    return value


# ------------------------------------------------------------------ journeys


class JourneyCreate(StrictModel):
    bus_id: uuid.UUID
    service_id: uuid.UUID
    departure_at: AwareDatetime
    scheduled_arrival_at: AwareDatetime
    timezone: str = "Asia/Kolkata"

    _tz = field_validator("timezone")(_valid_timezone)

    @model_validator(mode="after")
    def check_times(self):
        if self.scheduled_arrival_at <= self.departure_at:
            raise ValueError("scheduled arrival must be after departure")
        if self.scheduled_arrival_at - self.departure_at > MAX_JOURNEY_DURATION:
            raise ValueError("a journey cannot be longer than 72 hours")
        return self


class JourneyUpdate(StrictModel):
    """Only a draft journey can change its bus or time zone. Times are fixed at creation."""

    bus_id: uuid.UUID | None = None
    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str | None) -> str | None:
        return None if value is None else _valid_timezone(value)


class JourneyOut(BaseModel):
    id: uuid.UUID
    bus_id: uuid.UUID
    bus_registration: str
    bus_capacity: int
    service_id: uuid.UUID
    origin_name: str
    destination_name: str
    route_template_id: uuid.UUID | None
    departure_at: datetime
    scheduled_arrival_at: datetime
    booking_eta_at: datetime
    timezone: str
    status: str
    manual_mode: bool
    plan_needs_review: bool
    public_counts_enabled: bool
    booked_passengers: int
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------ bookings


class PassengerIn(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    seat_number: str | None = Field(default=None, max_length=10)
    phone: str | None = Field(default=None, max_length=20, pattern=r"^\+?[0-9 -]{6,20}$")

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class BookingCreate(StrictModel):
    reference: str | None = Field(default=None, min_length=1, max_length=40)
    contact_name: str | None = Field(default=None, max_length=120)
    passenger_count: int = Field(ge=1, le=100)
    pickup_stop_name: StopName
    drop_stop_name: StopName
    passengers: list[PassengerIn] = Field(default_factory=list, max_length=100)

    @field_validator("pickup_stop_name", "drop_stop_name", "reference", "contact_name")
    @classmethod
    def clean_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @model_validator(mode="after")
    def check_consistency(self):
        if self.pickup_stop_name.lower() == self.drop_stop_name.lower():
            raise ValueError("pickup and drop stops must be different")
        if len(self.passengers) > self.passenger_count:
            raise ValueError("more passenger details than passenger_count")
        return self


class BookingUpdate(StrictModel):
    contact_name: str | None = Field(default=None, max_length=120)
    passenger_count: int | None = Field(default=None, ge=1, le=100)
    pickup_stop_name: StopName | None = None
    drop_stop_name: StopName | None = None

    @field_validator("pickup_stop_name", "drop_stop_name", "contact_name")
    @classmethod
    def clean_strings(cls, value: str | None) -> str | None:
        return None if value is None else (_clean_text(value) or None)


class PassengerOut(BaseModel):
    id: uuid.UUID
    name: str
    seat_number: str | None
    phone: str | None


class BookingOut(BaseModel):
    id: uuid.UUID
    journey_id: uuid.UUID
    reference: str
    contact_name: str | None
    passenger_count: int
    pickup_stop_name: str
    drop_stop_name: str
    pickup_stop_id: uuid.UUID | None
    drop_stop_id: uuid.UUID | None
    status: str
    passengers: list[PassengerOut]
    created_at: datetime
    updated_at: datetime


class BookingWriteResult(BaseModel):
    booking: BookingOut
    # True when total booked passengers exceed the bus capacity. Segment-level capacity is
    # checked precisely by plan validation once stops are confirmed.
    capacity_warning: bool


class ImportResult(BaseModel):
    created: int
    capacity_warning: bool
