"""RouteSync API application."""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import db
from app.api.v1 import buses, health, journeys, me, services
from app.config import get_settings
from app.domain.errors import DomainError
from app.logging import configure_logging, request_id_var

logger = logging.getLogger("routesync.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(get_settings().log_level)
    db.get_pool()
    yield
    db.close_pool()


def _request_id(incoming: str) -> str:
    if 0 < len(incoming) <= 64 and incoming.isprintable():
        return incoming
    return uuid.uuid4().hex


def create_app() -> FastAPI:
    app = FastAPI(title="RouteSync API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = _request_id(request.headers.get("x-request-id", ""))
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "%s %s -> %s in %.0fms",
                request.method,
                request.url.path,
                response.status_code,
                (time.perf_counter() - started) * 1000,
            )
            return response
        finally:
            request_id_var.reset(token)

    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        body: dict = {"detail": exc.message, "code": exc.code}
        if exc.details is not None:
            body["details"] = exc.details
        return JSONResponse(body, status_code=exc.status_code)

    app.include_router(health.router)
    v1 = APIRouter(prefix="/api/v1")
    for module in (me, buses, services, journeys):
        v1.include_router(module.router)
    app.include_router(v1)
    return app


app = create_app()
