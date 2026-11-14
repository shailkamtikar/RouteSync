"""Postgres connection pool."""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated

import psycopg
from fastapi import Depends, HTTPException, status
from psycopg_pool import ConnectionPool, PoolTimeout

from app.config import get_settings

logger = logging.getLogger(__name__)
_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            get_settings().database_url,
            min_size=1,
            max_size=get_settings().db_pool_max,
            open=False,
            kwargs={"connect_timeout": 5},
        )
        _pool.open(wait=False)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def check_db() -> bool:
    """Return True when the database answers a trivial query."""
    try:
        with get_pool().connection(timeout=3) as conn:
            conn.execute("select 1")
        return True
    except Exception:
        logger.warning("database readiness check failed")
        return False


@contextmanager
def acquire() -> Iterator[psycopg.Connection]:
    """A pooled connection, or a 503 when none frees up in time (never an unbounded wait)."""
    try:
        with get_pool().connection(timeout=get_settings().db_pool_timeout_s) as conn:
            yield conn
    except PoolTimeout as exc:
        logger.warning("connection pool exhausted")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The service is busy, please retry shortly",
            headers={"Retry-After": "2"},
        ) from exc


def get_conn() -> Iterator[psycopg.Connection]:
    """Request-scoped connection: commits when the request succeeds, rolls back on error."""
    with acquire() as conn:
        yield conn


def connect_later() -> Iterator[Callable[[], Iterator[psycopg.Connection]]]:
    """For endpoints that often need no database at all: the connection is opened only on demand,
    so a cache hit costs no pooled connection and no wait."""
    yield acquire


DbConn = Annotated[psycopg.Connection, Depends(get_conn)]
LazyDb = Annotated[Callable[[], Iterator[psycopg.Connection]], Depends(connect_later)]
