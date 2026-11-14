# Runbook: incidents

## Symptoms and first checks

| Symptom | Check | Likely cause and action |
|---|---|---|
| Operators cannot sign in (401) | `GET /readyz`; API log lines `token rejected: …` | Key endpoint unreachable or clock skew. The API retries and keeps known keys; a 10 s clock leeway is allowed. Check the server clock and Supabase status |
| Public page says "Live tracking is temporarily unavailable" | `GET /api/v1/public/track/<token>` | API down or sleeping (free Render instance). The keep-alive workflow pings every 30 min; wake it by opening `/healthz` |
| Positions stop updating, page shows "Location not live" | Device token valid? Journey still running? | A revoked token or a completed journey returns 401/409 to the device; the page states the position is not live rather than showing an old one as current |
| Route changes repeatedly | `GET /journeys/{id}/reroute/decisions` | Should not happen: hysteresis, cooldown and a per-journey cap are enforced. Turn on manual mode for the journey; set `REROUTE_AUTOAPPLY=false` to stop automatic changes system-wide |
| Routing errors (`routing_quota_exceeded`) | API log | openrouteservice quota. Journeys keep their current route; assignment falls back to the template geometry. Wait for the quota to reset or supply a new key |
| Assistant answers with a standard message | API log `assistant fallback: quota` | Gemini quota or outage. Tracking is unaffected. `COMPANION_ENABLED=false` hides the panel entirely |
| Database paused (Supabase free plan) | Supabase dashboard | Restore the project; the keep-alive workflow prevents this when configured |

## Kill switches

- Per journey: manual mode (monitor screen) stops automatic route changes.
- `REROUTE_AUTOAPPLY=false`: recommendations only.
- `COMPANION_ENABLED=false`: assistant off.
- Revoke a public link from the journey page; revoke a device token from the monitor.

## Rotating a leaked secret

1. Rotate at the provider first (Supabase service key or database password, openrouteservice, Gemini, MapTiler).
2. Update the environment (Render / Vercel dashboards, local `.env` files).
3. Restart the API.
4. Only then remove the value from git history if it was committed (`git filter-repo`), and force-push once.
