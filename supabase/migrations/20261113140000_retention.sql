-- Data retention: a function that removes old live data and manifests, to be run on a schedule.
-- Retention periods are configuration passed by the caller, not product decisions.

create function app.apply_retention(
  gps_days integer default 30,
  manifest_days integer default 30,
  snapshot_days integer default 7
) returns table (gps_positions bigint, eta_snapshots bigint, passengers bigint)
language plpgsql set search_path = ''
as $$
declare
  g bigint; e bigint; p bigint;
begin
  -- Position history older than gps_days, only for journeys that have ended.
  with gone as (
    delete from public.gps_positions x using public.journeys j
    where j.id = x.journey_id and j.status in ('completed', 'cancelled')
      and x.device_ts < now() - make_interval(days => gps_days)
    returning 1)
  select count(*) into g from gone;

  -- Old ETA snapshots; the latest one per journey is always kept.
  with gone as (
    delete from public.journey_eta_snapshots x
    where x.calculated_at < now() - make_interval(days => snapshot_days)
      and x.id <> (select id from public.journey_eta_snapshots y where y.journey_id = x.journey_id
                   order by calculated_at desc, id desc limit 1)
    returning 1)
  select count(*) into e from gone;

  -- Passenger-level manifests after the journey has ended. Booking rows stay without names.
  with gone as (
    delete from public.booking_passengers x using public.journeys j
    where j.id = x.journey_id and j.status in ('completed', 'cancelled')
      and j.scheduled_arrival_at < now() - make_interval(days => manifest_days)
    returning 1)
  select count(*) into p from gone;
  update public.bookings b set contact_name = null from public.journeys j
    where j.id = b.journey_id and j.status in ('completed', 'cancelled')
      and j.scheduled_arrival_at < now() - make_interval(days => manifest_days)
      and b.contact_name is not null;

  return query select g, e, p;
end;
$$;

revoke all on function app.apply_retention(integer, integer, integer) from public;
