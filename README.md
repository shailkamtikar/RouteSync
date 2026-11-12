# RouteSync

*Intelligence behind every journey.*

RouteSync is a bus journey management, route optimization and live passenger tracking platform.

## Structure

| Path | Purpose |
|---|---|
| `apps/web` | Next.js + TypeScript: operator dashboard and public tracking page |
| `apps/api` | FastAPI: application APIs, optimizer, ETA engine |
| `supabase` | SQL migrations and seed data |
| `scripts` | GPS simulator and helper scripts |
| `docs` | Product knowledge document, development playbook, ADRs, runbooks |

## Setup

Copy `.env.example` to `apps/api/.env` and `apps/web/.env.local` and fill in the values. Never commit real env files.

Map data © OpenStreetMap contributors.
