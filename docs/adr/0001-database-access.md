# ADR 0001: Database access

**Status:** accepted

## Decision
- The schema changes only through SQL migrations in `supabase/migrations`, applied with `supabase db push`.
- The FastAPI service connects directly to Postgres with a privileged role and enforces operator and journey scope in application code.
- Row Level Security is enabled on every private table as a second line of defence for any direct client access.
- The browser never receives the service-role key or the database URL.
- Development runs against the hosted `routesync-dev` project. It holds test data only.

## Consequences
- Every API query must filter by the operator resolved from the authenticated user, never by a client-supplied id.
- RLS tests run against the dev database and clean up their own rows.
