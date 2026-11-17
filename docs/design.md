# Interface design

## Principles

- **One next step.** Every screen says where the work stands and offers the action that moves it forward. A journey's header shows a single primary button (Submit plan, Assign route, Publish, Start boarding, Mark departed, Mark completed); the rare actions sit beside it.
- **Choose, do not type.** Cities come from a catalog of Maharashtra towns, never from free text or coordinates. Stops in a booking are picked from the route's own stop list, and a drop stop can only come after the pickup.
- **Say what is true.** Times are labelled estimates, simulated traffic is labelled simulated, a position that is not live is greyed out and explained, and the arrival promised at booking always sits beside the live prediction.
- **Calm by default.** Light and dark themes, one accent colour, status shown with colour and a word (never colour alone), motion limited to live indicators and respects reduced-motion.
- **Works on a phone.** The sidebar becomes a menu, tables become cards, and every screen is checked for sideways scrolling at 390 px.

## Building blocks

| Piece | Where |
|---|---|
| Colour, type and spacing tokens (light, dark, toggle) | `apps/web/src/app/globals.css` |
| Buttons, fields, tables, notices | `apps/web/src/components/ui.module.css` |
| Status badge, page header, dialog, confirm dialog, toasts, tabs, chips, stat tiles, empty and loading states | `apps/web/src/components/kit/` |
| Place picker (search as you type, keyboard friendly) and the ordered "road passes through" picker | `apps/web/src/components/kit/PlaceInput.tsx` |
| App shell: sidebar, theme switch, mobile menu | `apps/web/src/components/shell/` |
| Map: route lines with casing, stops, labelled buses, follows the theme | `apps/web/src/components/map/RouteMap.tsx` |

Dialogs use the native `dialog` element, so focus is trapped, Escape closes them and the page behind is inert. The place picker follows the ARIA combobox pattern. Toasts are announced politely.

## The Maharashtra catalog

- `apps/web/src/data/places.json`: 218 towns and cities with district, importance tier and alternative names (Aurangabad finds Chhatrapati Sambhajinagar, Ahmednagar finds Ahilyanagar). The first 72 are hand-checked (`scripts/build_places.py` compares them with the openrouteservice geocoder); the other 146 come from a one-off OpenStreetMap lookup (`scripts/extend_places.py`) that must land inside Maharashtra.
- `apps/web/src/data/corridors.json`: 16 origin and destination pairs, each with two or three named roads, the towns the road is steered through and the towns where the bus stops. The service dialog offers these as ready-made route options, and `scripts/seed_network.py` builds the demo network from the same file.

Routing snaps each point to a road within 900 m, because a town centre is not always on one (the optimiser accepts a road up to 1 km from a stop).

## Screens

| Screen | Purpose |
|---|---|
| Overview | Day at a glance, live network map with every bus under way, next departures, what needs action |
| Services | Searchable cards (each a small transit line), New service dialog with picker and corridor suggestions |
| Service | Map of every route option, option cards with distance, drive time and stops, stop timeline with add and remove, known corridors offered one by one |
| Journeys | Filter by stage and search; grouped as on the road, upcoming, being planned, past; New journey dialog estimates arrival from the road's drive time |
| Journey | Progress steps, one primary action, summary, tabs for route and stops, bookings (selects, CSV import, seat meter) and the passenger link |
| Monitor | Four live cards, map, stop timeline with arrived, boarded, alighted and departed controls, route control, simulated traffic, device token |
| Buses | Fleet cards with a number plate, seats and what each bus is doing |
| Passenger page | Mobile first: destination and next stop, promise against prediction, map, stop timeline, journey assistant; no passenger data |
