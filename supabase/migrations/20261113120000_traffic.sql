-- Traffic incidents on a route option. OpenStreetMap has no live traffic, so every incident
-- in this version is simulated and must be labelled as such wherever it is shown.

create table public.traffic_incidents (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null,
  route_template_id uuid not null,
  kind text not null check (kind in ('slow', 'closure')),
  multiplier double precision not null default 1 check (multiplier between 1 and 20),
  from_point extensions.geography(Point, 4326) not null,
  to_point extensions.geography(Point, 4326) not null,
  from_km double precision not null check (from_km >= 0),
  to_km double precision not null,
  description text check (length(description) <= 200),
  simulated boolean not null default true check (simulated),
  starts_at timestamptz not null default now(),
  ends_at timestamptz,
  created_by uuid,
  created_at timestamptz not null default now(),
  check (to_km > from_km),
  check (ends_at is null or ends_at > starts_at),
  foreign key (route_template_id, operator_id)
    references public.route_templates (id, operator_id)
);
create index traffic_incidents_template_idx on public.traffic_incidents (route_template_id, starts_at);

alter table public.traffic_incidents enable row level security;
revoke all on table public.traffic_incidents from anon, authenticated;
grant select on table public.traffic_incidents to authenticated;
create policy traffic_incidents_select_member on public.traffic_incidents
  for select to authenticated using (app.is_operator_member(operator_id));
