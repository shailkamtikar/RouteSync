# Reroute scenarios

These scenarios are automated in `apps/api/tests/db/test_reroute.py` and can be reproduced by hand with the simulator.

## Rules the engine follows

| Rule | Behaviour |
|---|---|
| Nothing wrong ahead | The route is kept and no routing request is made |
| Small gain | Kept: a change must save at least `REROUTE_MIN_SAVING_MINUTES` and `REROUTE_MIN_SAVING_PCT` |
| Meaningful gain | Applied only after the same alternative wins `REROUTE_CONFIRMATIONS` evaluations in a row |
| After a change | No further automatic change for `REROUTE_COOLDOWN_MINUTES`, and at most `REROUTE_MAX_PER_JOURNEY` per journey |
| Road closed on the current route | An approved alternative is applied at once; with none, the journey is marked disrupted and the operator is alerted |
| Manual mode, or `REROUTE_AUTOAPPLY=false` | The engine only recommends; the operator approves |
| Position older than `GPS_STALE_AFTER_S` | No change |
| Routing provider unavailable | No change |
| A stop was passed with no recorded event | No change; the operator is asked to record the stop |

Every candidate must serve all remaining active stops in order and stay inside the route option's corridor. A candidate that fails either check is never scored.

All threshold values are tuning defaults, not product decisions.

## Scenario: slowdown between Beed and Parbhani

1. Journey running on the northern Pune-Nanded option, bus near Ahmednagar, active stops Beed and Parbhani, with an approved "Northern bypass" variant.
2. A simulated slowdown (20 times slower over about 6 km) is added on the main road between the two stops.
3. First evaluation: `keep / awaiting_confirmation`.
4. Second evaluation: `reroute / meaningful_saving`. Route version 2 (`auto_reroute`) is created, the operator gets an alert, and the decision log holds both entries with score breakdowns.
5. Further evaluations: the route is not changed again.

## Kill switches

- Per journey: turn on manual mode on the monitor screen.
- Whole system: set `REROUTE_AUTOAPPLY=false` and restart the API.
