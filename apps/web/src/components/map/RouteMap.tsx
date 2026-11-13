"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import type { GeoJSONSource, Map as MapLibreMap, Marker } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import {
  boundsOf,
  routeFeatures,
  stopFeatures,
  type MapBus,
  type MapRoute,
  type MapStop,
} from "@/lib/mapData";

import styles from "./RouteMap.module.css";

type Props = {
  routes?: MapRoute[];
  stops?: MapStop[];
  bus?: MapBus | null;
  height?: number;
};

const MAP_KEY = process.env.NEXT_PUBLIC_MAP_KEY ?? "";
const STYLE_URL = `https://api.maptiler.com/maps/streets-v2/style.json?key=${MAP_KEY}`;
const EMPTY: never[] = [];

/**
 * Map of one journey: route line(s), stops, pass-through places and the bus.
 * Tiles come from a hosted OpenStreetMap-based provider; attribution is always shown.
 */
export function RouteMap({ routes = EMPTY, stops = EMPTY, bus = null, height = 420 }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const busMarker = useRef<Marker | null>(null);
  const fitted = useRef(false);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!MAP_KEY || !container.current) return;
    let cancelled = false;
    let map: MapLibreMap | null = null;

    import("maplibre-gl")
      .then((maplibregl) => {
        if (cancelled || !container.current) return;
        maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
        const created = new maplibregl.Map({
          container: container.current,
          style: STYLE_URL,
          center: [75.6, 18.9],
          zoom: 6,
          attributionControl: false,
        });
        map = created;
        created.addControl(new maplibregl.AttributionControl({ compact: false }));
        created.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
        created.on("error", (event) => {
          // Style or tile failures (bad key, quota, offline) show the fallback message.
          if (!created.isStyleLoaded()) setFailed(true);
          console.warn("map error", event.error?.message);
        });
        created.on("load", () => {
          if (cancelled) return;
          created.addSource("routes", { type: "geojson", data: routeFeatures([]) });
          created.addSource("stops", { type: "geojson", data: stopFeatures([]) });
          created.addLayer({
            id: "routes-other",
            type: "line",
            source: "routes",
            filter: ["!", ["get", "selected"]],
            layout: { "line-cap": "round", "line-join": "round" },
            paint: { "line-color": ["get", "color"], "line-width": 3, "line-opacity": 0.45 },
          });
          created.addLayer({
            id: "routes-selected",
            type: "line",
            source: "routes",
            filter: ["get", "selected"],
            layout: { "line-cap": "round", "line-join": "round" },
            paint: { "line-color": ["get", "color"], "line-width": 5 },
          });
          created.addLayer({
            id: "stops-circle",
            type: "circle",
            source: "stops",
            paint: {
              "circle-radius": ["match", ["get", "kind"], "pass_through", 4, 7],
              "circle-color": [
                "match",
                ["get", "kind"],
                "pass_through",
                "#9ca3af",
                "suggested",
                "#ffffff",
                ["match", ["get", "status"], "completed", "#6b7280", "next", "#16a34a", "#1f6feb"],
              ],
              "circle-stroke-width": 2,
              "circle-stroke-color": ["match", ["get", "kind"], "suggested", "#1f6feb", "#ffffff"],
            },
          });
          created.addLayer({
            id: "stops-label",
            type: "symbol",
            source: "stops",
            layout: {
              "text-field": ["get", "label"],
              "text-size": ["match", ["get", "kind"], "pass_through", 11, 13],
              "text-offset": [0, 1.1],
              "text-anchor": "top",
              "text-optional": true,
            },
            paint: {
              "text-color": ["match", ["get", "kind"], "pass_through", "#6b7280", "#111827"],
              "text-halo-color": "#ffffff",
              "text-halo-width": 1.5,
            },
          });
          mapRef.current = created;
          setReady(true);
        });
      })
      .catch(() => setFailed(true));

    return () => {
      cancelled = true;
      busMarker.current = null;
      mapRef.current = null;
      fitted.current = false;
      map?.remove();
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource("routes") as GeoJSONSource | undefined)?.setData(routeFeatures(routes));
    (map.getSource("stops") as GeoJSONSource | undefined)?.setData(stopFeatures(stops));
    const bounds = boundsOf(routes, stops, bus);
    if (bounds && !fitted.current) {
      map.fitBounds(bounds, { padding: 48, maxZoom: 13, duration: 0 });
      fitted.current = true;
    }
  }, [ready, routes, stops, bus]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (!bus) {
      busMarker.current?.remove();
      busMarker.current = null;
      return;
    }
    let disposed = false;
    import("maplibre-gl").then((maplibregl) => {
      if (disposed || !mapRef.current) return;
      let marker = busMarker.current;
      if (!marker) {
        const created = document.createElement("div");
        created.setAttribute("role", "img");
        marker = new maplibregl.Marker({ element: created }).setLngLat([bus.lng, bus.lat]);
        marker.addTo(mapRef.current);
        busMarker.current = marker;
      }
      const element = marker.getElement();
      element.className = bus.stale ? `${styles.bus} ${styles.busStale}` : styles.bus;
      element.setAttribute("aria-label", bus.stale ? "Bus (location not live)" : "Bus");
      marker.setLngLat([bus.lng, bus.lat]);
    });
    return () => {
      disposed = true;
    };
  }, [ready, bus]);

  if (!MAP_KEY || failed) {
    return (
      <div className={styles.fallback} style={{ height }} role="status">
        {MAP_KEY
          ? "The map could not be loaded right now. Journey details below are still up to date."
          : "The map is unavailable because no map key is configured."}
      </div>
    );
  }
  return (
    <div className={styles.frame} style={{ height }}>
      <div ref={container} className={styles.map} aria-label="Journey map" />
    </div>
  );
}
