import { notFound } from "next/navigation";

import { RouteMap } from "@/components/map/RouteMap";
import type { MapRoute, MapStop } from "@/lib/mapData";

const ROUTES: MapRoute[] = [
  {
    id: "north",
    name: "Via Ahmednagar and Beed",
    selected: true,
    coordinates: [
      [73.8567, 18.5204],
      [74.7496, 19.0948],
      [75.7601, 18.9891],
      [76.7748, 19.2608],
      [77.321, 19.1383],
    ],
  },
  {
    id: "south",
    name: "Via Solapur and Latur",
    selected: false,
    coordinates: [
      [73.8567, 18.5204],
      [75.9064, 17.6599],
      [76.5604, 18.4088],
      [77.321, 19.1383],
    ],
  },
];

const STOPS: MapStop[] = [
  { id: "a", name: "Ahmednagar", lng: 74.7496, lat: 19.0948, kind: "active", status: "completed" },
  { id: "b", name: "Beed", lng: 75.7601, lat: 18.9891, kind: "active", status: "next" },
  { id: "c", name: "Parbhani", lng: 76.7748, lat: 19.2608, kind: "suggested" },
  { id: "d", name: "Majalgaon", lng: 76.208, lat: 19.151, kind: "pass_through" },
];

/** Development-only preview of the map component. */
export default function DevMapPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return (
    <main style={{ padding: 16, display: "grid", gap: 16 }}>
      <h1>Map preview</h1>
      <RouteMap routes={ROUTES} stops={STOPS} bus={{ lng: 75.2, lat: 19.05, stale: false }} />
      <h2>Stale bus, no route</h2>
      <RouteMap stops={STOPS} bus={{ lng: 75.2, lat: 19.05, stale: true }} height={260} />
    </main>
  );
}
