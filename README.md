# RouteSync

*Intelligence behind every journey.*

RouteSync is a bus journey management, route optimization and live passenger tracking platform. An operator configures each departure (service, route option, confirmed passenger stops, bookings); a journey-aware engine routes the bus through every confirmed stop and only changes the road when it is clearly worth it; passengers follow the bus on a public page with honest arrival times and an assistant that answers questions about that one journey.

## What it does

| Area | Highlights |
|---|---|
| Operator dashboard | Buses, services, route options drawn on an OpenStreetMap-based map, route-specific stops (with OpenStreetMap suggestions the operator must confirm), bookings with CSV import, plan validation, a journey lifecycle with audited transitions, versioned route plans |
| Live journey | Authenticated GPS ingestion (a simulator stands in for a device), operator-recorded stop events and verified on-board counts, simulated traffic (always labelled), one ETA snapshot that every screen reads, the arrival promised at booking kept beside the live prediction |
| Rerouting | Whole-journey candidates that must serve every active stop in order and stay inside the approved corridor; multi-objective scoring with an explainable breakdown; automatic changes only after a meaningful saving confirmed twice, with cooldown, a per-journey cap and a manual-mode switch; every decision logged |
| Passenger page | Unguessable, revocable link; two ETA cards, a stop timeline, pass-through towns marked "No passenger stop", "location not live" when positions are old, zero passenger data |
| RouteSync Companion | Gemini-based assistant bound server-side to the link's journey, limited to read-only tools, arithmetic done in the backend, answers scrubbed for private data, evaluated against golden and adversarial questions |

## Stack

Next.js (TypeScript) on Vercel · FastAPI (Python 3.12) on Render · Supabase Postgres with PostGIS and row level security · MapLibre GL JS with MapTiler tiles (OpenStreetMap data) · openrouteservice for road routing · Overpass for place suggestions · Gemini (`gemini-3.5-flash-lite`) for the assistant · UptimeRobot for monitoring.

## Repository

```
apps/web        Next.js app: operator dashboard, public tracking page, Companion panel
apps/api        FastAPI service: domain logic, optimizer, ETA engine, providers, Companion
supabase        SQL migrations (schema, RLS, triggers, retention)
scripts         seed_dev.py, demo_setup.py, gps_simulator.py, retention.py, reset_dev_data.py
docs            Knowledge document, playbook, ADRs, ERD, scenarios, edge cases, security, runbooks, eval reports
.github         CI (api-tests, web-tests), keep-alive and retention schedules
```

## Local setup

Requirements: Git, Node (latest), Python 3.12, a Supabase project, and keys for openrouteservice, MapTiler and Gemini.

```bash
git clone https://github.com/shailkamtikar/RouteSync.git && cd RouteSync
cp .env.example apps/api/.env          # fill in the server-side values
cp .env.example apps/web/.env.local    # keep only the NEXT_PUBLIC_* values here
```

```bash
cd apps/api && python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
npx supabase db push --remote="$DATABASE_URL"       # apply migrations
.venv/Scripts/python ../../scripts/seed_dev.py       # test operators and users
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

```bash
cd apps/web && npm install && npm run dev            # http://localhost:3000
```

Sign in as `owner1@routesync.test` with the password that `seed_dev.py` wrote to `apps/api/.env` (`SEED_USER_PASSWORD`).

### Environment variables

| Variable | Where | Purpose |
|---|---|---|
| `DATABASE_URL` | api | Supabase session-pooler connection string |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | api | Auth key verification and admin user creation |
| `ORS_API_KEY` | api | openrouteservice |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | api | Assistant (backend only) |
| `PUBLIC_TOKEN_PEPPER` | api | Mixed into stored token hashes |
| `COMPANION_ENABLED`, `REROUTE_AUTOAPPLY`, `GPS_MAX_SPEED_KMH` | api | Behaviour switches |
| `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_MAP_KEY` | web | Browser-visible configuration only |

Never commit `.env` files; only `.env.example` is tracked.

## Running a demo

```bash
apps/api/.venv/Scripts/python scripts/demo_setup.py --status boarding --out demo.json
apps/api/.venv/Scripts/python scripts/gps_simulator.py --token <device token from demo.json> --speed 40
```

`demo.json` holds the monitor URL, the public tracking URL and the device token. The full walkthrough is in `docs/demo-script.md`.

## Tests

```bash
cd apps/api && .venv/Scripts/python -m pytest -q            # unit tests (no network)
cd apps/api && .venv/Scripts/python -m pytest -q -m db      # against the dev database (rolled back)
cd apps/api && .venv/Scripts/python -m pytest -q -m live    # one-off checks against real providers
cd apps/api && .venv/Scripts/python -m app.companion.eval --live --report ../../docs/eval/report.md
cd apps/web && npm test && npm run e2e                      # unit and browser tests
```

CI runs lint, type checks, unit tests and the web build on every push.

## Documents

- `docs/RouteSync_Knowledge.md`: product requirements (the source of truth)
- `docs/RouteSync_Playbook.md`: phase-by-phase development playbook
- `docs/adr/`: decisions on database access, tiles, routing and the assistant model
- `docs/scenarios.md`, `docs/edge-cases.md`, `docs/security.md`, `docs/perf.md`
- `docs/runbooks/`: deploy, incident, rollback
- `docs/eval/report.md`: the assistant's latest live evaluation

## Attribution and licences

Map data © OpenStreetMap contributors (ODbL). Tiles © MapTiler. Routing by openrouteservice (HeiGIT). Place suggestions via the Overpass API. These credits are shown in the application.
