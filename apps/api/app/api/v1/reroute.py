"""Reroute decisions: log, operator re-evaluation, manual mode, approved variants."""

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import Field

from app.auth.deps import CurrentOperator
from app.db import DbConn
from app.domain import reroute
from app.domain.routing import Routing
from app.schemas.fleet import LatLng, StrictModel
from app.schemas.journeys import JourneyOut

router = APIRouter(tags=["reroute"])


class ManualModeIn(StrictModel):
    enabled: bool


class EvaluateIn(StrictModel):
    # True applies the suggested change now (operator approval).
    apply: bool = False


class VariantIn(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    points: list[LatLng] = Field(min_length=1, max_length=5)


class VariantsIn(StrictModel):
    variants: list[VariantIn] = Field(max_length=5)


@router.get("/journeys/{journey_id}/reroute/decisions", response_model=list[dict[str, Any]])
def list_decisions(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return reroute.list_decisions(conn, ctx, journey_id)


@router.post("/journeys/{journey_id}/reroute/evaluate", response_model=dict[str, Any])
def evaluate(
    journey_id: uuid.UUID, data: EvaluateIn, ctx: CurrentOperator, conn: DbConn, provider: Routing
):
    return reroute.operator_evaluate(conn, ctx, journey_id, provider, data.apply)


@router.put("/journeys/{journey_id}/manual-mode", response_model=JourneyOut)
def set_manual_mode(journey_id: uuid.UUID, data: ManualModeIn, ctx: CurrentOperator, conn: DbConn):
    return reroute.set_manual_mode(conn, ctx, journey_id, data.enabled)


@router.put("/route-templates/{template_id}/variants", response_model=dict[str, Any])
def set_variants(template_id: uuid.UUID, data: VariantsIn, ctx: CurrentOperator, conn: DbConn):
    return reroute.set_variants(conn, ctx, template_id, [v.model_dump() for v in data.variants])
