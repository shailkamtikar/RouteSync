"""Postgres connection pool."""

import logging
from collections.abc import Iterator
from typing import Annotated

import psycopg
from fastapi import Depends
from psycopg_pool import ConnectionPool

from app.config import get_settings

logger = logging.getLogger(__name__)
_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            get_settings().database_url,
            min_size=1,
            max_size=5,
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


def get_conn() -> Iterator[psycopg.Connection]:
    """Request-scoped connection: commits when the request succeeds, rolls back on error."""
    with get_pool().connection() as conn:
        yield conn


DbConn = Annotated[psycopg.Connection, Depends(get_conn)]
