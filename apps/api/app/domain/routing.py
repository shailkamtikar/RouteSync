"""Routing service: provider selection plus a database cache that saves provider quota."""

import hashlib
import json
import logging
from dataclasses import asdict
from functools import lru_cache
from typing import Annotated

import psycopg
from fastapi import Depends
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.providers.routing.base import (
    Leg,
    LngLat,
    RouteResult,
    RoutingProvider,
    RoutingUnavailable,
    validate_request,
)
from app.providers.routing.ors import OrsRoutingProvider

logger = logging.getLogger(__name__)
CACHE_VERSION = 2


class _Unconfigured:
    name = "unconfigured"
    max_waypoints = 50

    def route(self, waypoints, *, profile="driving-car", alternatives=0):
        raise RoutingUnavailable("routing provider is not configured")


@lru_cache
def _default_provider() -> RoutingProvider:
    key = get_settings().ors_api_key
    return OrsRoutingProvider(key) if key else _Unconfigured()


def get_routing_provider() -> RoutingProvider:
    return _default_provider()


Routing = Annotated[RoutingProvider, Depends(get_routing_provider)]


def cache_key(provider: str, waypoints: list[LngLat], profile: str, alternatives: int) -> str:
    request = {
        "v": CACHE_VERSION,
        "provider": provider,
        "profile": profile,
        "alternatives": alternatives,
        "waypoints": [[round(lng, 5), round(lat, 5)] for lng, lat in waypoints],
    }
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()


def _to_json(results: list[RouteResult]) -> list[dict]:
    return [asdict(result) for result in results]


def _from_json(rows: list[dict]) -> list[RouteResult]:
    return [
        RouteResult(
            coordinates=[(c[0], c[1]) for c in row["coordinates"]],
            distance_m=row["distance_m"],
            duration_s=row["duration_s"],
            legs=[Leg(**leg) for leg in row["legs"]],
            provider=row["provider"],
            metadata=row.get("metadata", {}),
            warnings=row.get("warnings", []),
            waypoint_indices=row.get("waypoint_indices", []),
        )
        for row in rows
    ]


def route(
    conn: psycopg.Connection,
    provider: RoutingProvider,
    waypoints: list[LngLat],
    *,
    profile: str = "driving-car",
    alternatives: int = 0,
    use_cache: bool = True,
) -> list[RouteResult]:
    """Return routes from the cache, or ask the provider and remember the answer."""
    validate_request(waypoints, profile, alternatives, provider.max_waypoints)
    key = cache_key(provider.name, waypoints, profile, alternatives)
    if use_cache:
        cached = conn.execute(
            "select response from public.routing_cache where key = %s", (key,)
        ).fetchone()
        if cached:
            try:
                return _from_json(cached[0])
            except (KeyError, TypeError, IndexError):
                logger.warning("ignoring unreadable routing cache entry")
    results = provider.route(waypoints, profile=profile, alternatives=alternatives)
    conn.execute(
        "insert into public.routing_cache (key, provider, response) values (%s, %s, %s) "
        "on conflict (key) do update set response = excluded.response, created_at = now()",
        (key, provider.name, Jsonb(_to_json(results))),
    )
    return results
