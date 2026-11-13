"""Request and response models for the stop plan, validation, lifecycle and route versions."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.fleet import LatLng, StrictModel


class ActiveStopIn(StrictModel):
    route_template_stop_id: uuid.UUID
    pickup_count: int = Field(ge=0, le=100)
    drop_count: int = Field(ge=0, le=100)
    dwell_minutes: int = Field(default=5, ge=0, le=120)


class ActiveStopsIn(StrictModel):
    stops: list[ActiveStopIn] = Field(max_length=50)


class StopPlanRow(BaseModel):
    route_template_stop_id: uuid.UUID
    name: str
    role: str
    kind: str
    chainage_m: float | None
    location: LatLng
    active: bool
    sequence: int | None
    pickup_count: int
    drop_count: int
    dwell_minutes: int
    # Hints from confirmed bookings. They never activate a stop by themselves.
    booked_pickups: int
    booked_drops: int


class StopPlanOut(BaseModel):
    route_template_id: uuid.UUID | None
    editable: bool
    plan_needs_review: bool
    stops: list[StopPlanRow]
    unresolved_bookings: list[dict]


class IssueOut(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    message: str
    details: dict


class ValidationOut(BaseModel):
    valid: bool
    issues: list[IssueOut]


class TransitionIn(StrictModel):
    to: Literal[
        "draft",
        "awaiting_confirmation",
        "ready",
        "published",
        "boarding",
        "in_progress",
        "completed",
        "cancelled",
        "disrupted",
    ]


class TransitionsOut(BaseModel):
    status: str
    allowed: list[str]


class RouteVersionOut(BaseModel):
    id: uuid.UUID
    version: int
    distance_m: float | None
    duration_s: float | None
    reason: str
    source: str
    details: dict
    is_current: bool
    coordinates: list[tuple[float, float]]
    created_at: datetime
