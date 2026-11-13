/** Pure helpers that turn journey data into GeoJSON for the map. No map library imports. */

export type LngLat = [number, number];

export type MapRoute = {
  id: string;
  name: string;
  coordinates: LngLat[];
  color?: string;
  /** Unselected route options are drawn thinner and semi-transparent. */
  selected?: boolean;
};

export type MapStopKind = "active" | "suggested" | "pass_through";

export type MapStop = {
  id: string;
  name: string;
  lng: number;
  lat: number;
  kind: MapStopKind;
  status?: "completed" | "next" | "upcoming";
};

export type MapBus = { lng: number; lat: number; stale: boolean };

export const ROUTE_COLORS = ["#1f6feb", "#d97706", "#7c3aed", "#0f766e"];
export const PASS_THROUGH_LABEL = "No passenger stop";

function isValid([lng, lat]: LngLat): boolean {
  return Number.isFinite(lng) && Number.isFinite(lat) && Math.abs(lng) <= 180 && Math.abs(lat) <= 90;
}

export function routeFeatures(routes: MapRoute[]) {
  return {
    type: "FeatureCollection" as const,
    features: routes
      .map((route, index) => ({ route, index, coordinates: route.coordinates.filter(isValid) }))
      .filter(({ coordinates }) => coordinates.length >= 2)
      .map(({ route, index, coordinates }) => ({
        type: "Feature" as const,
        properties: {
          id: route.id,
          name: route.name,
          color: route.color ?? ROUTE_COLORS[index % ROUTE_COLORS.length],
          selected: route.selected ?? true,
        },
        geometry: { type: "LineString" as const, coordinates },
      })),
  };
}

export function stopFeatures(stops: MapStop[]) {
  return {
    type: "FeatureCollection" as const,
    features: stops
      .filter((stop) => isValid([stop.lng, stop.lat]))
      .map((stop) => ({
        type: "Feature" as const,
        properties: {
          id: stop.id,
          kind: stop.kind,
          status: stop.status ?? "upcoming",
          // A pass-through town is never presented as a passenger stop.
          label: stop.kind === "pass_through" ? `${stop.name}\n${PASS_THROUGH_LABEL}` : stop.name,
        },
        geometry: { type: "Point" as const, coordinates: [stop.lng, stop.lat] as LngLat },
      })),
  };
}

/** Bounding box [[west, south], [east, north]] of everything shown, or null when empty. */
export function boundsOf(
  routes: MapRoute[],
  stops: MapStop[],
  bus?: MapBus | null,
): [LngLat, LngLat] | null {
  const points: LngLat[] = [
    ...routes.flatMap((route) => route.coordinates),
    ...stops.map((stop): LngLat => [stop.lng, stop.lat]),
    ...(bus ? [[bus.lng, bus.lat] as LngLat] : []),
  ].filter(isValid);
  if (points.length === 0) return null;
  let [west, south] = points[0];
  let [east, north] = points[0];
  for (const [lng, lat] of points) {
    west = Math.min(west, lng);
    east = Math.max(east, lng);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  return [
    [west, south],
    [east, north],
  ];
}
