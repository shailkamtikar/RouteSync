"""openrouteservice adapter. Called only from the backend; the key never reaches the browser."""

import logging
import time

import httpx

from app.providers.routing.base import (
    Leg,
    LngLat,
    RouteResult,
    RoutingInvalidRequest,
    RoutingQuotaExceeded,
    RoutingUnavailable,
    alternatives_allowed,
    validate_request,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.openrouteservice.org/v2/directions"
ATTRIBUTION = "© openrouteservice.org by HeiGIT | Map data © OpenStreetMap contributors"
ALTERNATIVES_WARNING = "alternatives_unavailable"


class OrsRoutingProvider:
    name = "openrouteservice"
    max_waypoints = 50

    def __init__(
        self,
        api_key: str,
        *,
        timeout_s: float = 10.0,
        retries: int = 2,
        backoff_s: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ):
        if not api_key:
            raise RoutingUnavailable("routing provider is not configured")
        self._retries = retries
        self._backoff_s = backoff_s
        self._client = httpx.Client(
            timeout=timeout_s,
            transport=transport,
            headers={"Authorization": api_key, "Accept": "application/geo+json"},
        )

    def route(
        self, waypoints: list[LngLat], *, profile: str = "driving-car", alternatives: int = 0
    ) -> list[RouteResult]:
        validate_request(waypoints, profile, alternatives, self.max_waypoints)
        warnings: list[str] = []
        body: dict = {"coordinates": [list(point) for point in waypoints], "instructions": True}
        if alternatives:
            if alternatives_allowed(waypoints):
                body["alternative_routes"] = {
                    "target_count": alternatives + 1,
                    "share_factor": 0.6,
                    "weight_factor": 1.6,
                }
            else:
                warnings.append(ALTERNATIVES_WARNING)
        payload = self._post(f"{BASE_URL}/{profile}/geojson", body)
        return self._parse(payload, warnings, legs_expected=len(waypoints) - 1)

    def _post(self, url: str, body: dict) -> dict:
        last_error = "no attempt made"
        for attempt in range(self._retries + 1):
            if attempt:
                time.sleep(self._backoff_s * attempt)
            try:
                response = self._client.post(url, json=body)
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
                continue
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:
                    raise RoutingUnavailable("routing provider returned malformed data") from None
            if response.status_code == 429:
                raise RoutingQuotaExceeded("routing quota or rate limit exhausted")
            if response.status_code in (401, 403):
                # ORS answers 403 for both a bad key and an exhausted daily quota.
                if "quota" in response.text.lower():
                    raise RoutingQuotaExceeded("routing quota exhausted")
                raise RoutingUnavailable("routing provider rejected the credentials")
            if 400 <= response.status_code < 500:
                raise RoutingInvalidRequest(self._error_message(response))
            last_error = f"HTTP {response.status_code}"
        logger.warning("routing provider unavailable: %s", last_error)
        raise RoutingUnavailable("routing provider is unavailable")

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = "the route could not be calculated"
        return str(message)[:300]

    def _parse(self, payload: dict, warnings: list[str], legs_expected: int) -> list[RouteResult]:
        """Turn the provider's GeoJSON into RouteResult objects (turn-by-turn steps are dropped)."""
        try:
            results = []
            for feature in payload["features"]:
                properties = feature["properties"]
                coordinates = [
                    (float(c[0]), float(c[1])) for c in feature["geometry"]["coordinates"]
                ]
                if len(coordinates) < 2:
                    raise ValueError("empty geometry")
                distance = float(properties["summary"]["distance"])
                duration = float(properties["summary"]["duration"])
                legs = [
                    Leg(float(s["distance"]), float(s["duration"]))
                    for s in properties.get("segments", [])
                ]
                if not legs and legs_expected == 1:
                    legs = [Leg(distance, duration)]
                if len(legs) != legs_expected:
                    raise ValueError("leg count does not match the waypoints")
                indices = [int(i) for i in properties.get("way_points", [])]
                if len(indices) != legs_expected + 1 or indices != sorted(indices):
                    raise ValueError("waypoint indices do not match the waypoints")
                results.append(
                    RouteResult(
                        coordinates=coordinates,
                        distance_m=distance,
                        duration_s=duration,
                        legs=legs,
                        provider=self.name,
                        metadata={"attribution": ATTRIBUTION},
                        warnings=list(warnings),
                        waypoint_indices=indices,
                    )
                )
            if not results:
                raise ValueError("no routes")
            return results
        except (KeyError, TypeError, ValueError, IndexError):
            raise RoutingUnavailable("routing provider returned malformed data") from None
