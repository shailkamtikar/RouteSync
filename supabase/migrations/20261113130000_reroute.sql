-- Reroute decisions: an auditable log of every evaluation that considered a change,
-- per-journey anti-flapping state, and approved corridor variants on route options.

alter table public.route_templates
  add column variants jsonb not null default '[]';

alter table public.journeys
  add column reroute_pending_name text,
  add column reroute_pending_count integer not null default 0 check (reroute_pending_count >= 0),
  add column last_reroute_eval_at timestamptz;

create table public.route_decisions (
  id bigint generated always as identity primary key,
  operator_id uuid not null,
  journey_id uuid not null,
  decided_at timestamptz not null default now(),
  outcome text not null check (outcome in ('keep', 'recommend', 'reroute', 'no_feasible_route')),
  reason_code text not null,
  reason text not null,
  chosen_name text,
  saving_minutes double precision,
  route_version_id uuid,
  trigger text not null default 'position' check (trigger in ('position', 'operator')),
  details jsonb not null default '{}',
  foreign key (journey_id, operator_id) references public.journeys (id, operator_id),
  foreign key (route_version_id, journey_id) references public.route_versions (id, journey_id)
);
create index route_decisions_journey_idx on public.route_decisions (journey_id, decided_at desc);
create trigger route_decisions_append_only before update or delete on public.route_decisions
  for each row execute function app.forbid_change();

alter table public.route_decisions enable row level security;
revoke all on table public.route_decisions from anon, authenticated;
grant select on table public.route_decisions to authenticated;
create policy route_decisions_select_member on public.route_decisions
  for select to authenticated using (app.is_operator_member(operator_id));
