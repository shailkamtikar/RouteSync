-- Route template stops: mark the two journey endpoints, and cache OSM place lookups.

alter table public.route_template_stops
  add column role text not null default 'intermediate'
  check (role in ('origin', 'intermediate', 'destination'));

-- Exactly one origin and one destination stop per route template at most.
create unique index route_template_stops_one_origin_key
  on public.route_template_stops (route_template_id) where role = 'origin';
create unique index route_template_stops_one_destination_key
  on public.route_template_stops (route_template_id) where role = 'destination';

-- Endpoints are always passenger stops.
alter table public.route_template_stops
  add constraint route_template_stops_endpoint_kind
  check (role = 'intermediate' or kind = 'passenger_stop');

-- Cache of OpenStreetMap place lookups (public map data only).
create table public.places_cache (
  key text primary key check (length(key) = 64),
  response jsonb not null,
  created_at timestamptz not null default now()
);
alter table public.places_cache enable row level security;
revoke all on table public.places_cache from anon, authenticated;
