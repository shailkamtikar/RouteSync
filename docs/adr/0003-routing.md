# ADR 0003: Routing provider

**Status:** accepted

## Decision
- Road routing goes through a `RoutingProvider` interface (`apps/api/app/providers/routing`). The app never calls a routing vendor directly, so the vendor can be swapped.
- The production implementation is openrouteservice (ORS). A deterministic fake provider is used in automated tests, so tests never spend quota.
- Every answer is cached in the `routing_cache` table, keyed by a hash of the request.
- A route option for a service is an operator-defined corridor (ordered via-points) turned into geometry by the provider. Provider "alternative routes" are requested only for a single leg of 100 km or less.

## Verified against the live service (November 2026)
| Check | Result |
|---|---|
| Pune to Nanded, `driving-car` | 431 km, about 5.1 h |
| Pune to Nanded, `driving-hgv` | 431 km, about 5.4 h |
| Ordered waypoints | Legs and `way_points` indices come back in request order |
| Per-leg distance and duration | Returned only when `instructions` is enabled, so the adapter enables it and discards the turn-by-turn steps |
| Alternatives on a 16 km leg | 3 routes returned |
| Rate-limit header | `X-Ratelimit-Limit: 200`; the window is not stated in the response |

## Limits taken from the provider's published restrictions
- 50 waypoints per route.
- Alternatives: at most 3, only up to 100 km, and only between two points.

## Failure handling
| Situation | Behaviour |
|---|---|
| Invalid request (bad coordinates, too many waypoints) | Rejected before any provider call, HTTP 422 |
| Timeout or 5xx | Retried twice, then HTTP 503 `routing_unavailable` |
| 429 or quota exhausted | Not retried, HTTP 503 `routing_quota_exceeded` |
| Malformed response | HTTP 503 `routing_unavailable`, nothing cached |

## Open item
The account's real daily quota must be read from the openrouteservice dashboard; published figures differ between pages.
