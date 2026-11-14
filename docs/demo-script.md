# Demo script (about 7 minutes)

## Before the demo

```bash
# terminal 1
cd apps/api && .venv/Scripts/python -m uvicorn app.main:app --port 8000
# terminal 2
cd apps/web && npm run dev
# terminal 3: a complete journey, ready to board
apps/api/.venv/Scripts/python scripts/demo_setup.py --status boarding --out demo.json
```

`demo.json` holds the monitor URL, the public tracking URL and the device token. Open the monitor in one window (sign in as `owner1@routesync.test`) and the tracking URL in a private window or a phone.

## 1. The operator's plan (1 min)

Open the journey page from the monitor's "Journey setup" link. Show the route option on the map, the confirmed active stops with the booking-derived hints, and the route version. Mention: stops are confirmed by the operator, never activated automatically; the plan was validated before assignment.

## 2. Departure (1 min)

On the monitor: Pune → **Arrived**, enter 5 → **Boarded**, **Departed**. The status becomes "in progress", the on-board count shows 5 from recorded boardings. On the passenger page the status changes to "On the way" and Pune shows as done.

## 3. The bus moves (1 min)

```bash
apps/api/.venv/Scripts/python scripts/gps_simulator.py --token <device token from demo.json> --speed 40
```

The marker moves along the route on both screens; the two ETA cards and the progress bar update every few seconds. Stop the simulator for two minutes to show the "Location not live" banner and the grey marker, then start it again.

## 4. Traffic and rerouting (2 min)

On the monitor, add a simulated incident: slow traffic, km 250 to 290, 3 times slower. Both screens show "Simulated slow traffic ahead" and the arrival time moves later; the promise made at booking stays as it was. Explain the engine: a change needs a meaningful saving confirmed twice, respects a cooldown and a cap, and never skips a stop or leaves the corridor. Turn on manual mode to show that the engine then only recommends.

## 5. The assistant (1.5 min)

On the passenger page, tap "How many stops are left?", then type "Does this bus pass through Latur?" and "Cancel my booking". Point out: answers come from the journey's own data, it says what is not shared, and it directs booking changes to the operator.

## 6. Arrival (0.5 min)

Record Beed (arrived, 3 alighted, departed) and Nanded (arrived, finish). The passenger page shows "Journey completed". Revoke the link from the journey page and reload the passenger page: "Tracking unavailable".
