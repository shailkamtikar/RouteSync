"""Route preview for operators (used while defining route options)."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.auth.deps import CurrentOperator
from app.db import DbConn
from app.domain import routing
from app.domain.routing import Routing
from app.schemas.fleet import LatLng, StrictModel

router = APIRouter(prefix="/routing", tags=["routing"])


class RoutePreviewRequest(StrictModel):
    waypoints: list[LatLng] = Field(min_length=2, max_length=50)
    profile: Literal["driving-car", "driving-hgv"] = "driving-car"
    alternatives: int = Field(default=0, ge=0, le=3)


class RouteOut(BaseModel):
    coordinates: list[tuple[float, float]]
    distance_m: float
    duration_s: float
    legs: list[dict]
    provider: str
    attribution: str | None
    warnings: list[str]


def to_route_out(result) -> RouteOut:
    return RouteOut(
        coordinates=result.coordinates,
        distance_m=result.distance_m,
        duration_s=result.duration_s,
        legs=[{"distance_m": leg.distance_m, "duration_s": leg.duration_s} for leg in result.legs],
        provider=result.provider,
        attribution=result.metadata.get("attribution"),
        warnings=result.warnings,
    )


@router.post("/preview", response_model=list[RouteOut])
def preview(data: RoutePreviewRequest, ctx: CurrentOperator, conn: DbConn, provider: Routing):
    waypoints = [(point.lng, point.lat) for point in data.waypoints]
    results = routing.route(
        conn, provider, waypoints, profile=data.profile, alternatives=data.alternatives
    )
    return [to_route_out(result) for result in results]
