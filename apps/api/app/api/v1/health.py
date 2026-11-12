"""Liveness and readiness endpoints."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import db

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> JSONResponse:
    if db.check_db():
        return JSONResponse({"status": "ok", "db": "ok"})
    return JSONResponse({"status": "unavailable", "db": "unavailable"}, status_code=503)
