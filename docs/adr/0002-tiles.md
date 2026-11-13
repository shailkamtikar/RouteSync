# ADR 0002: Map rendering and tiles

**Status:** accepted

## Decision
- Maps are rendered with MapLibre GL JS (vector tiles, smooth marker updates, styleable labels).
- Tiles and the base style come from MapTiler's hosted OpenStreetMap-based service on its free plan. The public `tile.openstreetmap.org` servers are not used.
- The map key is a browser-visible key (`NEXT_PUBLIC_MAP_KEY`). It must be restricted to the app's origins in the provider dashboard.
- Attribution ("© MapTiler © OpenStreetMap contributors") is always displayed and cannot be collapsed.
- The MapLibre worker file is copied from `node_modules` into `public/maplibre/` before `dev` and `build`, so it is served from the app's own origin.

## Consequences
- If the key is missing, or the style cannot load, the map shows a text fallback and the rest of the page keeps working.
- If the free allowance is exhausted, the fallback is self-hosted tiles (PMTiles); only the style URL changes.
