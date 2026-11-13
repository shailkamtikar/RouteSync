"""Request and response models for simulated traffic incidents."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.fleet import StrictModel


class TrafficIncidentCreate(StrictModel):
    kind: Literal["slow", "closure"] = "slow"
    # Stretch of the route option, in kilometres from its start.
    from_km: float = Field(ge=0, le=5000)
    to_km: float = Field(gt=0, le=5000)
    # How many times longer the stretch takes. Ignored for a closure.
    multiplier: float = Field(default=2.0, ge=1.0, le=20.0)
    duration_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    description: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def check_range(self):
        if self.to_km <= self.from_km:
            raise ValueError("to_km must be greater than from_km")
        return self


class TrafficIncidentOut(BaseModel):
    id: uuid.UUID
    route_template_id: uuid.UUID
    kind: str
    multiplier: float
    from_km: float
    to_km: float
    description: str | None
    simulated: bool
    starts_at: datetime
    ends_at: datetime | None
