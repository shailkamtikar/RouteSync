"""Current operator profile."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from app.auth.deps import CurrentOperator

router = APIRouter(tags=["me"])


class MeResponse(BaseModel):
    user_id: uuid.UUID
    email: str | None
    operator_id: uuid.UUID
    operator_name: str
    role: str


@router.get("/me", response_model=MeResponse)
def me(ctx: CurrentOperator) -> MeResponse:
    return MeResponse(
        user_id=ctx.user_id,
        email=ctx.email,
        operator_id=ctx.operator_id,
        operator_name=ctx.operator_name,
        role=ctx.role,
    )
