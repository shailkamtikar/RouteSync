# Performance notes

Measured locally on 2026-11-14 (API on a laptop, Supabase hosted database in another region, one
demo journey in `boarding`, viewers polling the public tracking endpoint as fast as they can).

## Public tracking endpoint

| Scenario | Throughput | p50 | p95 | Errors |
|---|---|---|---|---|
| 20 viewers x 10 requests, no pause | 54 req/s | 6 ms | 2.8 s | none |
| 50 viewers x 10 requests, no pause | 320 req/s | 126 ms | 184 ms | 100 x 429 |
| 200 viewers x 5 requests, 2 s pause | 93 req/s | 21 ms | 275 ms | 1000 x 429 |

The p95 of the first run is the cost of building a view against the remote database (several
PostGIS queries plus one ETA snapshot). Every other viewer of the same link within
`PUBLIC_VIEW_CACHE_S` (default 3 s) is served from memory and needs no database connection.

The 429 responses come from the per-address limit (`PUBLIC_RATE_PER_MIN_IP`, default 600/min):
all test viewers share one address, which real passengers do not. The per-link limit
(`PUBLIC_RATE_PER_MIN_TOKEN`, default 900/min) allows 90 passengers polling every 10 s.

## What was fixed along the way

Before these changes the 50-viewer run returned nothing but 30 s timeouts. Sync FastAPI handlers
run on a thread pool, and the connection was taken in a dependency that ran before the handler.
Under load every thread was held by a request waiting for a connection, so the requests holding
connections could not get a thread to finish: a deadlock. Three changes remove it:

1. the thread pool is sized well above the connection pool (`WORKER_THREADS`, default 100, versus
   `DB_POOL_MAX`, default 10);
2. waiting for a connection is bounded (`DB_POOL_TIMEOUT_S`, default 10 s) and answers 503 with
   `Retry-After` instead of hanging;
3. the public endpoint opens a connection only on a cache miss.

The ETA service also checks for a fresh stored snapshot with one query before computing anything,
so operator and passenger screens polling the same journey share one calculation.

## Known limits

- Everything above is one API process. The caches are per process; a second instance would miss
  separately, which is correct but costs one extra database pass per instance.
- Database latency dominates: the API and the database should be deployed in the same region.
- Routing provider calls (openrouteservice) are cached in `routing_cache`; a cold reroute
  evaluation still waits on the provider, which is why evaluation runs on its own interval and
  never inside a GPS ingestion request.
