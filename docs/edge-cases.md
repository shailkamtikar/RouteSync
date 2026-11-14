# Edge cases: expected behaviour

Each row names the automated check that proves it.

| # | Situation | Backend | Operator sees | Passenger sees | Audit | Proof |
|---|---|---|---|---|---|---|
| 1 | Journey has no bookings or no intermediate stops | Validation warns (not an error); ETA treats the destination as the next endpoint | "No bookings" note; plan can still be assigned | Destination card is the next stop | `route_assigned` | `test_planning_api::test_journey_without_bookings_only_warns`, `test_failure_drills::test_journey_without_intermediate_stops` |
| 2 | Booking added, changed or cancelled after stops were confirmed | `plan_needs_review` set; stop plan never rewritten; `ready` blocked until reconfirmed | Review banner on the journey page | No change | `booking_*` | `test_planning_api::test_booking_change_after_confirmation_requires_review` |
| 3 | A booking's pickup or drop stop is not on the selected route option | Reported as unresolved; blocks assignment | Named in the plan panel | — | — | `test_routes_api::test_select_route_option_and_resolve_booking_stops` |
| 4 | Drop ordered before pickup | Validation error `DROP_BEFORE_PICKUP` | Listed as a problem | — | — | `test_validation::test_drop_before_pickup` |
| 5 | Stop with both pickups and drops | Accepted; seats freed before boarding | Both counts shown | Both counts if sharing is on | — | `test_planning_api::test_stop_with_both_pickup_and_drop_is_accepted` |
| 6 | GPS delayed, duplicated, out of order, inaccurate, unavailable | Duplicates ignored; late points stored without moving the latest back; impossible jumps rejected; stale flagged | "Location not live" banner, grey marker | Same banner, grey marker; plan-based times when none | — | `test_gps_ingest`, `test_eta_api::test_stale_gps_is_flagged` |
| 7 | Traffic data unavailable | There is no live feed by design; incidents are simulated and labelled | "Simulated" in every alert | "Simulated" in every alert | — | `test_traffic_api` |
| 8 | Road closed after departure | Current route blocked; approved alternative applied at once, or journey marked disrupted | Alert, decision log entry | Closure alert | `route_rerouted` / `journey_transition` | `test_reroute::test_closure_*` |
| 9 | Alternative violates the corridor or misses a stop | Never scored; rejected by hard constraints | — | — | — | `test_constraints_and_candidates` |
| 10 | Alternative offers a small gain | Kept (`below_threshold`) | Decision log | — | `route_decisions` | `test_reroute::test_marginal_slowdown_does_not_change_the_route` |
| 11 | Bus delayed beyond the booking promise | Promise kept; delay reported; one public delay alert | Promise vs now expected | Same, with "Running N min late" | `delay_alert_opened` | `test_commitment_alerts`, `test_failure_drills::test_delay_beyond_the_promise_*` |
| 12 | Public link revoked or expired | 410, no data | Link status | "Tracking unavailable" | `tracking_link_revoked` | `test_public_track::test_revoked_and_expired_links_are_gone` |
| 13 | Two journeys on the same service and option at once | Separate stops, positions, snapshots, alerts, links | Separate monitors | Separate pages | — | `test_failure_drills::test_two_journeys_same_route_same_time_never_share_state`, golden scenario |
| 14 | Journey completed or cancelled | Positions refused (409); status shown | Completed/cancelled badge | Finished card | `journey_transition` | `test_stop_events_api::test_finishing_at_the_destination_completes_the_journey` |
| 15 | Operator opens another operator's journey | 404 everywhere | "Journey not found" | — | — | `test_security_matrix` (177 checks) |
| 16 | Routing or places provider fails, times out or runs out of quota | Retry then 503; cached answers reused; assignment falls back to template geometry; reroute keeps the route; suggestions unavailable | Clear message | Unaffected | — | `test_routing_providers`, `test_failure_drills::test_routing_quota_exhausted_keeps_journeys_running` |
| 17 | Assistant model down, blocked or out of quota | Standard fallback message; tracking unaffected | — | Fallback message in the chat | — | `test_companion_chat::test_model_failures_degrade_gracefully` |
| 18 | A stop was passed with no event recorded | ETA warns; reroute engine refuses to act; operator alert | "Record the stop" alert | Stop still shown as pending | — | `test_reroute::test_stop_passed_without_a_recorded_event_never_triggers_a_reroute` |
