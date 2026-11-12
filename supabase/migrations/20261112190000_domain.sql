-- Domain schema: fleet, routes, journeys, bookings, live journey data, audit.
-- Every row carries operator_id for tenant scoping. Composite foreign keys make the
-- database itself guarantee journey isolation (a child row cannot point at another
-- journey's or another operator's parent).

create extension if not exists btree_gist with schema extensions;
set search_path = public, extensions;

create function app.touch_updated_at() returns trigger
language plpgsql set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create function app.forbid_change() returns trigger
language plpgsql set search_path = ''
as $$
begin
  raise exception '% on % is not allowed: rows are immutable', tg_op, tg_table_name
    using errcode = 'restrict_violation';
end;
$$;

-- ---------------------------------------------------------------- fleet and routes

create table public.buses (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null references public.operators (id),
  registration text not null check (length(btrim(registration)) between 1 and 20),
  capacity integer not null check (capacity between 1 and 100),
  vehicle_constraints jsonb not null default '{}',
  status text not null default 'active' check (status in ('active', 'archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, operator_id)
);
create unique index buses_operator_registration_key
  on public.buses (operator_id, upper(btrim(registration)));

create table public.services (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null references public.operators (id),
  origin_name text not null check (length(btrim(origin_name)) between 1 and 120),
  destination_name text not null check (length(btrim(destination_name)) between 1 and 120),
  origin_location geography(Point, 4326),
  destination_location geography(Point, 4326),
  status text not null default 'active' check (status in ('active', 'archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (lower(btrim(origin_name)) <> lower(btrim(destination_name))),
  unique (id, operator_id)
);

-- A route option (corridor) for a service. Its stop list is specific to this template.
create table public.route_templates (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null,
  service_id uuid not null,
  name text not null check (length(btrim(name)) between 1 and 120),
  version integer not null default 1 check (version >= 1),
  via_points jsonb not null default '[]',
  profile text not null default 'driving-car',
  geometry geography(LineString, 4326),
  corridor geography(Polygon, 4326),
  distance_m double precision check (distance_m >= 0),
  duration_s double precision check (duration_s >= 0),
  provider text,
  provider_metadata jsonb not null default '{}',
  status text not null default 'unresolved' check (status in ('unresolved', 'ready', 'archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (service_id, operator_id) references public.services (id, operator_id),
  unique (id, operator_id),
  unique (id, service_id)
);
create index route_templates_service_idx on public.route_templates (service_id);
create index route_templates_geometry_idx on public.route_templates using gist (geometry);

create table public.route_template_stops (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null,
  route_template_id uuid not null,
  name text not null check (length(btrim(name)) between 1 and 120),
  location geography(Point, 4326) not null,
  chainage_m double precision check (chainage_m >= 0),
  kind text not null default 'passenger_stop' check (kind in ('passenger_stop', 'pass_through')),
  source text not null default 'operator' check (source in ('operator', 'osm')),
  created_at timestamptz not null default now(),
  foreign key (route_template_id, operator_id) references public.route_templates (id, operator_id),
  unique (id, route_template_id)
);
create unique index route_template_stops_name_key
  on public.route_template_stops (route_template_id, lower(btrim(name)));

-- ---------------------------------------------------------------- journeys and bookings

create table public.journeys (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null,
  bus_id uuid not null,
  service_id uuid not null,
  route_template_id uuid,
  departure_at timestamptz not null,
  scheduled_arrival_at timestamptz not null,
  -- Arrival expectation communicated at booking time. Never changes after insert.
  booking_eta_at timestamptz not null,
  timezone text not null default 'Asia/Kolkata',
  status text not null default 'draft' check (status in (
    'draft', 'awaiting_confirmation', 'ready', 'published', 'boarding',
    'in_progress', 'completed', 'cancelled', 'disrupted')),
  manual_mode boolean not null default false,
  plan_needs_review boolean not null default false,
  public_counts_enabled boolean not null default false,
  current_route_version_id uuid,
  last_position geography(Point, 4326),
  last_position_at timestamptz,
  last_device_ts timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (scheduled_arrival_at > departure_at),
  foreign key (bus_id, operator_id) references public.buses (id, operator_id),
  foreign key (service_id, operator_id) references public.services (id, operator_id),
  foreign key (route_template_id, service_id) references public.route_templates (id, service_id),
  unique (id, operator_id),
  unique (id, route_template_id),
  -- One bus cannot run two overlapping journeys (cancelled journeys do not count).
  constraint journeys_bus_no_overlap exclude using gist (
    bus_id with =, tstzrange(departure_at, scheduled_arrival_at) with &&
  ) where (status <> 'cancelled')
);
create index journeys_operator_departure_idx on public.journeys (operator_id, departure_at desc);

create function app.protect_booking_eta() returns trigger
language plpgsql set search_path = ''
as $$
begin
  if new.booking_eta_at is distinct from old.booking_eta_at then
    raise exception 'booking_eta_at is immutable' using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;
create trigger journeys_protect_booking_eta before update on public.journeys
  for each row execute function app.protect_booking_eta();

create table public.bookings (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null,
  journey_id uuid not null,
  reference text not null check (length(btrim(reference)) between 1 and 40),
  contact_name text check (length(contact_name) <= 120),
  passenger_count integer not null check (passenger_count between 1 and 100),
  pickup_stop_name text not null check (length(btrim(pickup_stop_name)) between 1 and 120),
  drop_stop_name text not null check (length(btrim(drop_stop_name)) between 1 and 120),
  pickup_stop_id uuid references public.route_template_stops (id),
  drop_stop_id uuid references public.route_template_stops (id),
  status text not null default 'confirmed' check (status in ('confirmed', 'cancelled')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (lower(btrim(pickup_stop_name)) <> lower(btrim(drop_stop_name))),
  check (pickup_stop_id is null or drop_stop_id is null or pickup_stop_id <> drop_stop_id),
  foreign key (journey_id, operator_id) references public.journeys (id, operator_id),
  unique (id, journey_id),
  unique (journey_id, reference)
);

create table public.booking_passengers (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null,
  journey_id uuid not null,
  booking_id uuid not null,
  name text not null check (length(btrim(name)) between 1 and 120),
  seat_number text check (length(seat_number) <= 10),
  phone text check (length(phone) <= 20),
  created_at timestamptz not null default now(),
  foreign key (journey_id, operator_id) references public.journeys (id, operator_id),
  foreign key (booking_id, journey_id) references public.bookings (id, journey_id) on delete cascade,
  unique (id, journey_id)
);
create index booking_passengers_booking_idx on public.booking_passengers (booking_id);

-- Operator-confirmed active stops for one journey. Stops must come from the journey's
-- own route template (composite foreign keys on route_template_id).
create table public.journey_stops (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null,
  journey_id uuid not null,
  route_template_id uuid not null,
  route_template_stop_id uuid not null,
  sequence integer not null check (sequence >= 1),
  pickup_count integer not null default 0 check (pickup_count >= 0),
  drop_count integer not null default 0 check (drop_count >= 0),
  dwell_minutes integer not null default 5 check (dwell_minutes between 0 and 120),
  status text not null default 'pending' check (status in ('pending', 'arrived', 'departed')),
  arrived_at timestamptz,
  departed_at timestamptz,
  created_at timestamptz not null default now(),
  check (pickup_count + drop_count > 0),
  foreign key (journey_id, operator_id) references public.journeys (id, operator_id),
  foreign key (journey_id, route_template_id) references public.journeys (id, route_template_id),
  foreign key (route_template_stop_id, route_template_id)
    references public.route_template_stops (id, route_template_id),
  unique (id, journey_id),
  unique (journey_id, route_template_stop_id),
  unique (journey_id, sequence) deferrable initially deferred
);

create table public.journey_stop_passengers (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null,
  journey_id uuid not null,
  journey_stop_id uuid not null,
  booking_passenger_id uuid not null,
  action text not null check (action in ('pickup', 'drop')),
  foreign key (journey_id, operator_id) references public.journeys (id, operator_id),
  foreign key (journey_stop_id, journey_id)
    references public.journey_stops (id, journey_id) on delete cascade,
  foreign key (booking_passenger_id, journey_id)
    references public.booking_passengers (id, journey_id) on delete cascade,
  unique (booking_passenger_id, action)
);

-- ---------------------------------------------------------------- live journey data

create table public.route_versions (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null,
  journey_id uuid not null,
  version integer not null check (version >= 1),
  geometry geography(LineString, 4326) not null,
  distance_m double precision check (distance_m >= 0),
  duration_s double precision check (duration_s >= 0),
  reason text not null,
  source text not null check (source in ('operator_initial', 'auto_reroute', 'operator_reroute')),
  details jsonb not null default '{}',
  created_by uuid,
  created_at timestamptz not null default now(),
  foreign key (journey_id, operator_id) references public.journeys (id, operator_id),
  unique (id, journey_id),
  unique (journey_id, version)
);
create trigger route_versions_immutable before update on public.route_versions
  for each row execute function app.forbid_change();

alter table public.journeys
  add constraint journeys_current_route_version_fk
  foreign key (current_route_version_id, id) references public.route_versions (id, journey_id);

create table public.gps_positions (
  id bigint generated always as identity primary key,
  operator_id uuid not null,
  journey_id uuid not null,
  location geography(Point, 4326) not null,
  accuracy_m double precision check (accuracy_m >= 0),
  speed_mps double precision check (speed_mps >= 0),
  device_ts timestamptz not null,
  received_at timestamptz not null default now(),
  source text not null check (length(source) between 1 and 40),
  foreign key (journey_id, operator_id) references public.journeys (id, operator_id),
  unique (journey_id, device_ts, source)
);
create index gps_positions_journey_ts_idx on public.gps_positions (journey_id, device_ts desc);

create table public.stop_events (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null,
  journey_id uuid not null,
  journey_stop_id uuid not null,
  type text not null check (type in ('arrived', 'departed', 'boarded', 'alighted')),
  count integer not null default 0 check (count >= 0),
  client_event_id text not null check (length(client_event_id) between 1 and 80),
  occurred_at timestamptz not null,
  recorded_by uuid,
  created_at timestamptz not null default now(),
  foreign key (journey_id, operator_id) references public.journeys (id, operator_id),
  foreign key (journey_stop_id, journey_id) references public.journey_stops (id, journey_id),
  unique (journey_id, client_event_id)
);

create table public.journey_eta_snapshots (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null,
  journey_id uuid not null,
  route_version_id uuid,
  calculated_at timestamptz not null default now(),
  next_stop_eta timestamptz,
  destination_eta timestamptz,
  payload jsonb not null,
  foreign key (journey_id, operator_id) references public.journeys (id, operator_id),
  foreign key (route_version_id, journey_id) references public.route_versions (id, journey_id)
);
create index journey_eta_snapshots_latest_idx
  on public.journey_eta_snapshots (journey_id, calculated_at desc);

create table public.journey_alerts (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null,
  journey_id uuid not null,
  type text not null check (length(type) between 1 and 60),
  severity text not null check (severity in ('info', 'warning', 'critical')),
  message text not null check (length(message) between 1 and 500),
  is_public boolean not null default false,
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  foreign key (journey_id, operator_id) references public.journeys (id, operator_id)
);
-- At most one open alert of each type per journey.
create unique index journey_alerts_one_open_key
  on public.journey_alerts (journey_id, type) where resolved_at is null;

-- Only a hash of the public token is stored.
create table public.public_tracking_links (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null,
  journey_id uuid not null,
  token_hash text not null unique check (length(token_hash) = 64),
  created_at timestamptz not null default now(),
  expires_at timestamptz,
  revoked_at timestamptz,
  foreign key (journey_id, operator_id) references public.journeys (id, operator_id)
);
create unique index public_tracking_links_one_active_key
  on public.public_tracking_links (journey_id) where revoked_at is null;

-- Append-only audit trail. journey_id is null for operator-level entities (bus, service...).
create table public.journey_events (
  id bigint generated always as identity primary key,
  operator_id uuid not null references public.operators (id),
  journey_id uuid,
  actor_id uuid,
  event_type text not null check (length(event_type) between 1 and 80),
  entity_type text,
  entity_id uuid,
  payload jsonb not null default '{}',
  created_at timestamptz not null default now(),
  foreign key (journey_id, operator_id) references public.journeys (id, operator_id)
);
create index journey_events_journey_idx on public.journey_events (journey_id, created_at);
create index journey_events_operator_idx on public.journey_events (operator_id, created_at desc);
create trigger journey_events_append_only before update or delete on public.journey_events
  for each row execute function app.forbid_change();

-- ---------------------------------------------------------------- updated_at triggers

do $$
declare t text;
begin
  foreach t in array array['buses', 'services', 'route_templates', 'journeys', 'bookings'] loop
    execute format(
      'create trigger %I before update on public.%I for each row execute function app.touch_updated_at()',
      t || '_touch_updated_at', t);
  end loop;
end $$;

-- ---------------------------------------------------------------- row level security
-- Members may read their own operator's rows. All writes go through the API.
-- The anonymous role gets no privileges at all.

do $$
declare t text;
begin
  foreach t in array array[
    'buses', 'services', 'route_templates', 'route_template_stops', 'journeys', 'bookings',
    'booking_passengers', 'journey_stops', 'journey_stop_passengers', 'route_versions',
    'gps_positions', 'stop_events', 'journey_eta_snapshots', 'journey_alerts',
    'public_tracking_links', 'journey_events'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on table public.%I from anon, authenticated', t);
    execute format('grant select on table public.%I to authenticated', t);
    execute format(
      'create policy %I on public.%I for select to authenticated using (app.is_operator_member(operator_id))',
      t || '_select_member', t);
  end loop;
end $$;

-- Token hashes are never readable through the data API, even by members.
revoke select on table public.public_tracking_links from authenticated;
