"""Request and response models for the live journey (positions, stop events, traffic)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from app.schemas.fleet import StrictModel


class GpsPointIn(StrictModel):
    device_ts: AwareDatetime
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=10_000)
    speed_mps: float | None = Field(default=None, ge=0, le=100)
    source: str = Field(default="device", min_length=1, max_length=40, pattern=r"^[\w.-]+$")


class GpsBatchIn(StrictModel):
    points: list[GpsPointIn] = Field(min_length=1, max_length=50)


class GpsIngestResult(BaseModel):
    accepted: int
    duplicates: int
    rejected: list[dict]


class IngestTokenOut(BaseModel):
    # Shown once. Only a hash is stored.
    token: str


class DeviceRouteOut(BaseModel):
    distance_m: float | None
    duration_s: float | None
    coordinates: list[tuple[float, float]]


class StopEventIn(StrictModel):
    journey_stop_id: uuid.UUID
    type: Literal["arrived", "departed", "boarded", "alighted"]
    count: int = Field(default=0, ge=0, le=100)
    client_event_id: str = Field(min_length=1, max_length=80, pattern=r"^[\w.:-]+$")
    occurred_at: AwareDatetime | None = None


class StopEventOut(BaseModel):
    id: uuid.UUID
    journey_stop_id: uuid.UUID
    type: str
    count: int
    client_event_id: str
    occurred_at: datetime
    duplicate: bool = False
    journey_status: str
    onboard: dict
