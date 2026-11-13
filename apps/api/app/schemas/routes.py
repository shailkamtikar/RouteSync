"""Request and response models for route templates (route options) and their stops."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.fleet import LatLng, StrictModel, _clean_text

Profile = Literal["driving-car", "driving-hgv"]
MAX_VIA_POINTS = 20


class ViaPoint(StrictModel):
    name: str | None = Field(default=None, max_length=120)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


def _clean_name(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        raise ValueError("must not be blank")
    return cleaned


class RouteTemplateCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    via_points: list[ViaPoint] = Field(default_factory=list, max_length=MAX_VIA_POINTS)
    profile: Profile = "driving-car"

    _name = field_validator("name")(_clean_name)


class RouteTemplateUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    via_points: list[ViaPoint] | None = Field(default=None, max_length=MAX_VIA_POINTS)
    profile: Profile | None = None

    @field_validator("name")
    @classmethod
    def clean(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)


class RouteTemplateOut(BaseModel):
    id: uuid.UUID
    service_id: uuid.UUID
    name: str
    version: int
    via_points: list[ViaPoint]
    profile: str
    status: str
    distance_m: float | None
    duration_s: float | None
    provider: str | None
    attribution: str | None
    # Simplified line for map display, as [lng, lat] pairs. Empty until generated.
    coordinates: list[tuple[float, float]]
    stop_count: int
    created_at: datetime
    updated_at: datetime


class RouteTemplateWriteResult(BaseModel):
    template: RouteTemplateOut
    # Set when the geometry could not be generated; the template stays "unresolved".
    generation_error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class SelectRouteTemplate(StrictModel):
    route_template_id: uuid.UUID


# ------------------------------------------------------------------ stops


class StopCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    location: LatLng
    kind: Literal["passenger_stop", "pass_through"] = "passenger_stop"
    source: Literal["operator", "osm"] = "operator"

    _name = field_validator("name")(_clean_name)


class StopUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: Literal["passenger_stop", "pass_through"] | None = None

    @field_validator("name")
    @classmethod
    def clean(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)


class StopOut(BaseModel):
    id: uuid.UUID
    route_template_id: uuid.UUID
    name: str
    location: LatLng
    chainage_m: float | None
    kind: str
    role: str
    source: str


class StopCandidate(BaseModel):
    name: str
    location: LatLng
    place_type: str
    chainage_m: float


class StopCandidatesOut(BaseModel):
    available: bool
    message: str | None = None
    attribution: str | None = None
    candidates: list[StopCandidate]


class ResolveStopsResult(BaseModel):
    resolved: int
    unresolved: list[dict]
