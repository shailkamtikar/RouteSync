# Data model

```
operators ─┬─ operator_members ── auth.users
           ├─ buses
           ├─ services ── route_templates ── route_template_stops
           └─ journeys (bus, service, route_template)
                 ├─ bookings ── booking_passengers
                 ├─ journey_stops (active stops, from the journey's own template)
                 │      └─ journey_stop_passengers
                 ├─ route_versions (immutable, numbered per journey)
                 ├─ gps_positions
                 ├─ stop_events
                 ├─ journey_eta_snapshots
                 ├─ journey_alerts
                 ├─ public_tracking_links (token hash only)
                 └─ journey_events (append-only audit)
```

## Rules enforced by the database

- Every row has `operator_id`; row level security lets members read only their operator's rows. The anonymous role has no privileges.
- Composite foreign keys stop a child row pointing at another journey or another operator.
- An active stop must belong to the journey's own route template.
- `journeys.booking_eta_at` cannot change after insert.
- A bus cannot have overlapping journeys (cancelled ones excluded).
- `route_versions` and `journey_events` cannot be updated; audit events cannot be deleted.
- Timestamps are stored in UTC and shown in the journey's time zone.
