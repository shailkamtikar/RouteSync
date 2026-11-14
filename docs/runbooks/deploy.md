# Runbook: deployment

Deployment was deferred until the end of development (the whole system was built and tested locally against the hosted dev database). These are the steps for a first deployment.

## Backend (Render)

- New Web Service from the GitHub repository; root directory `apps/api`.
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/healthz`
- Environment variables: every name in `.env.example` under `apps/api/.env`, with production values. `CORS_ORIGINS` must list the Vercel origin.
- Free instances sleep after 15 minutes idle and take about a minute to wake. The `keepalive` workflow pings `/readyz` every 30 minutes when the `API_URL` repository variable is set.

## Frontend (Vercel)

- Import the repository; root directory `apps/web`; framework Next.js.
- Environment variables: `NEXT_PUBLIC_API_BASE_URL` (the Render URL), `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_MAP_KEY`.
- The build copies the map worker into `public/maplibre` (`prebuild` script); nothing else to configure.
- Restrict the MapTiler key to the Vercel origin in the MapTiler dashboard.

## Database (Supabase)

- Apply migrations: `npx supabase db push --remote="$DATABASE_URL"`.
- Seed operators and test users: `python scripts/seed_dev.py` (dev only; create real operators by hand for production).
- Free projects pause after a week of low activity; the keep-alive workflow prevents this.

## Monitoring (UptimeRobot)

Monitors on the web URL, `<api>/healthz` and `<api>/readyz` at a 5-minute interval, with e-mail alerts. `/readyz` reports 503 when the database is unreachable.

## After deploying

1. `curl <api>/readyz` → `{"status":"ok","db":"ok"}`.
2. Sign in on the web URL and open a journey monitor.
3. Create a public link and open it in a private window.
4. Re-run the security header check: `curl -I <api>/healthz`.
