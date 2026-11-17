# Demo script (about 8 minutes)

## Before the demo

One-time: build the Maharashtra network (16 services, 33 route options, 20 buses and 20 journeys in every state). Run `reset_dev_data.py --yes` first if the database holds old test data.

```bash
apps/api/.venv/Scripts/python scripts/seed_network.py
```

Each time:

```bash
# terminal 1
cd apps/api && .venv/Scripts/python -m uvicorn app.main:app --port 8010
# terminal 2
cd apps/web && npm run dev
# terminal 3: keep every bus that is on the road moving (Ctrl+C to stop)
apps/api/.venv/Scripts/python scripts/fleet_simulator.py --speedup 30
# terminal 4: a Pune to Nanded journey that is boarding, with a passenger link
apps/api/.venv/Scripts/python scripts/demo_setup.py --out demo.json
```

`demo_setup.py` reuses the seeded journey, so running it again does not create anything new. `demo.json` holds the monitor URL, the passenger URL and the device token. Sign in at http://localhost:3000 as `owner1@routesync.test` (the password is `SEED_USER_PASSWORD` in `apps/api/.env`) and open the passenger URL in a private window or on a phone.

## 1. The overview (1 min)

The overview shows the day at a glance: buses on the road, boarding, departures in the next 24 hours, journeys that need action and passengers today. The map draws every bus that is under way on its own road, and the list beside it says who is early or late. Click a journey card to focus its route on the map.

## 2. The network (1 min)

Open **Services**: sixteen corridors across Maharashtra. Open Pune → Nanded: three different roads (through Ahilyanagar and Beed, through Baramati and Latur, through Chhatrapati Sambhajinagar and Jalna), each with its own stops. Add a route option by choosing the towns the road passes through. Create a new service and note that known corridors come with their route options.

## 3. The operator's plan (1 min)

Open a draft journey. The progress steps show where it is and the header offers exactly one next step. Choose the route option, add bookings from the stop lists, confirm the active stops and submit. Mention: stops are confirmed by the operator, never activated automatically, and the plan is validated before assignment.

## 4. Departure (1 min)

On the monitor of the boarding journey: Pune → **Arrived**, enter 5 → **Boarded**, **Departed**. The status becomes "In progress" and the on-board count shows 5 from recorded boardings. On the passenger page the status changes to "On the way" and Pune shows as done.

## 5. The bus moves (1 min)

```bash
apps/api/.venv/Scripts/python scripts/gps_simulator.py --token <device token from demo.json> --speed 40
```

The marker moves along the route on both screens; the two ETA cards and the progress bar update every few seconds. Stop the simulator for two minutes to show the "Location not live" banner and the grey marker, then start it again.

## 6. Traffic and rerouting (2 min)

On the monitor, add a simulated incident: slow traffic, km 250 to 290, 3 times slower. Both screens show "Simulated slow traffic ahead" and the arrival time moves later; the promise made at booking stays as it was. Explain the engine: a change needs a meaningful saving confirmed twice, respects a cooldown and a cap, and never skips a stop or leaves the corridor. Turn on manual mode to show that the engine then only recommends.

## 7. The assistant (1.5 min)

On the passenger page, tap "How many stops are left?", then type "Does this bus pass through Latur?" and "Cancel my booking". Point out: answers come from the journey's own data, it says what is not shared, and it directs booking changes to the operator.

## 8. Arrival (0.5 min)

Record the remaining stops (arrived, alighted, departed) and the destination (arrived, finish). The passenger page shows "Journey completed". Revoke the link from the journey's Passenger link tab and reload the passenger page: "Tracking unavailable".

Switch the theme with the moon icon in the sidebar to show the dark mode, and resize to phone width to show the menu.
