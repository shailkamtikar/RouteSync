"""Request and response models for buses and services."""

import re
import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REGISTRATION_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9 -]{2,18}[A-Z0-9]$")
PlaceName = Annotated[str, Field(min_length=1, max_length=120)]


def _clean_text(value: str) -> str:
    return " ".join(value.split())


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LatLng(StrictModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


# ------------------------------------------------------------------ buses


class BusCreate(StrictModel):
    registration: str
    capacity: int = Field(ge=1, le=100)
    vehicle_constraints: dict[str, Any] = Field(default_factory=dict)

    @field_validator("registration")
    @classmethod
    def normalise_registration(cls, value: str) -> str:
        cleaned = _clean_text(value).upper()
        if not REGISTRATION_PATTERN.fullmatch(cleaned):
            raise ValueError("registration must be 4-20 letters, digits, spaces or hyphens")
        return cleaned


class BusUpdate(StrictModel):
    registration: str | None = None
    capacity: int | None = Field(default=None, ge=1, le=100)
    vehicle_constraints: dict[str, Any] | None = None
    expected_updated_at: datetime | None = None

    @field_validator("registration")
    @classmethod
    def normalise_registration(cls, value: str | None) -> str | None:
        return None if value is None else BusCreate.normalise_registration(value)


class BusOut(BaseModel):
    id: uuid.UUID
    registration: str
    capacity: int
    vehicle_constraints: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------ services


class ServiceCreate(StrictModel):
    origin_name: PlaceName
    destination_name: PlaceName
    origin_location: LatLng | None = None
    destination_location: LatLng | None = None

    @field_validator("origin_name", "destination_name")
    @classmethod
    def clean_names(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @model_validator(mode="after")
    def origin_differs_from_destination(self):
        if self.origin_name.lower() == self.destination_name.lower():
            raise ValueError("origin and destination must be different")
        return self


class ServiceUpdate(StrictModel):
    origin_name: PlaceName | None = None
    destination_name: PlaceName | None = None
    origin_location: LatLng | None = None
    destination_location: LatLng | None = None
    expected_updated_at: datetime | None = None

    @field_validator("origin_name", "destination_name")
    @classmethod
    def clean_names(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class ServiceOut(BaseModel):
    id: uuid.UUID
    origin_name: str
    destination_name: str
    origin_location: LatLng | None
    destination_location: LatLng | None
    status: str
    created_at: datetime
    updated_at: datetime


class RemovalResult(BaseModel):
    result: str  # "deleted" or "archived"
