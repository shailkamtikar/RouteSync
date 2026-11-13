-- Cache of routing-provider answers, keyed by a hash of the request. Saves provider quota.
-- Holds road geometry only (no operator or passenger data). Not reachable through the data API.

create table public.routing_cache (
  key text primary key check (length(key) = 64),
  provider text not null,
  response jsonb not null,
  created_at timestamptz not null default now()
);

alter table public.routing_cache enable row level security;
revoke all on table public.routing_cache from anon, authenticated;
