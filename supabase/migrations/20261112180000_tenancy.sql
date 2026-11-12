-- Tenancy: operators, memberships, helper functions and row level security.

create table public.operators (
  id uuid primary key default gen_random_uuid(),
  name text not null check (length(btrim(name)) between 1 and 200),
  status text not null default 'active' check (status in ('active', 'suspended')),
  created_at timestamptz not null default now()
);

-- A user belongs to exactly one operator in v1 (unique user_id).
create table public.operator_members (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null references public.operators (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  role text not null check (role in ('owner', 'dispatcher')),
  created_at timestamptz not null default now(),
  unique (user_id)
);

create index operator_members_operator_id_idx on public.operator_members (operator_id);

-- Helper functions live in a schema that is not exposed through the data API.
create schema if not exists app;
grant usage on schema app to authenticated;

create function app.is_operator_member(op uuid) returns boolean
language sql stable security definer set search_path = ''
as $$
  select exists (
    select 1 from public.operator_members m
    where m.operator_id = op and m.user_id = (select auth.uid())
  );
$$;

create function app.is_operator_owner(op uuid) returns boolean
language sql stable security definer set search_path = ''
as $$
  select exists (
    select 1 from public.operator_members m
    where m.operator_id = op and m.user_id = (select auth.uid()) and m.role = 'owner'
  );
$$;

revoke all on function app.is_operator_member(uuid) from public;
revoke all on function app.is_operator_owner(uuid) from public;
grant execute on function app.is_operator_member(uuid) to authenticated;
grant execute on function app.is_operator_owner(uuid) to authenticated;

-- Default deny: RLS on, anonymous role has no table privileges at all.
alter table public.operators enable row level security;
alter table public.operator_members enable row level security;

revoke all on table public.operators from anon, authenticated;
revoke all on table public.operator_members from anon, authenticated;
grant select on table public.operators to authenticated;
grant select, insert, update, delete on table public.operator_members to authenticated;

create policy operators_select_member on public.operators
  for select to authenticated
  using (app.is_operator_member(id));

create policy operator_members_select_member on public.operator_members
  for select to authenticated
  using (app.is_operator_member(operator_id));

create policy operator_members_insert_owner on public.operator_members
  for insert to authenticated
  with check (app.is_operator_owner(operator_id));

create policy operator_members_update_owner on public.operator_members
  for update to authenticated
  using (app.is_operator_owner(operator_id))
  with check (app.is_operator_owner(operator_id));

create policy operator_members_delete_owner on public.operator_members
  for delete to authenticated
  using (app.is_operator_owner(operator_id));
