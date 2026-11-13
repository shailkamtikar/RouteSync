-- Per-journey credentials for the (simulated or real) GPS device. Only a hash is stored.

create table public.journey_ingest_tokens (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null,
  journey_id uuid not null,
  token_hash text not null unique check (length(token_hash) = 64),
  created_at timestamptz not null default now(),
  revoked_at timestamptz,
  foreign key (journey_id, operator_id) references public.journeys (id, operator_id)
);

create unique index journey_ingest_tokens_one_active_key
  on public.journey_ingest_tokens (journey_id) where revoked_at is null;

alter table public.journey_ingest_tokens enable row level security;
revoke all on table public.journey_ingest_tokens from anon, authenticated;
