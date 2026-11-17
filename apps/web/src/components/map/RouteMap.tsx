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

export type FleetBus = MapBus & { id: string; label?: string; color?: string };

type Props = {
  routes?: MapRoute[];
  stops?: MapStop[];
  bus?: MapBus | null;
  /** Several labelled buses (network overview). */
  fleet?: FleetBus[];
  height?: number | string;
  /** Called with the route id when a line is clicked. */
  onRouteClick?: (id: string) => void;
  /** Re-fit the view whenever the highlighted route changes. */
  fitKey?: string;
  label?: string;
};

const MAP_KEY = process.env.NEXT_PUBLIC_MAP_KEY ?? "";
const styleUrl = (dark: boolean) =>
  `https://api.maptiler.com/maps/basic-v2${dark ? "-dark" : "-light"}/style.json?key=${MAP_KEY}`;

function prefersDark(): boolean {
  const chosen = document.documentElement.dataset.theme;
  if (chosen) return chosen === "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}
const EMPTY: never[] = [];
const BUS_SVG =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6v6M16 6v6M2 12h19.6M18 18h3s.5-1.7.8-4.7c.2-2.5-.2-5.5-1.3-6.9A4 4 0 0 0 17.4 4H5.7a3 3 0 0 0-2.8 2.1C2 8.7 2 12.4 2 14c0 2.2.6 4 .6 4H6"/><circle cx="7" cy="18" r="2"/><path d="M9 18h5"/><circle cx="16" cy="18" r="2"/></svg>';

/**
 * Map of one journey or of the whole network: route lines, stops, pass-through places and buses.
 * Tiles come from a hosted OpenStreetMap-based provider; attribution is always shown.
 */
export function RouteMap({
  routes = EMPTY,
  stops = EMPTY,
  bus = null,
  fleet = EMPTY,
  height = 420,
  onRouteClick,
  fitKey,
  label = "Journey map",
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markers = useRef<Map<string, Marker>>(new Map());
  const fitted = useRef<string | null>(null);
  const clickRef = useRef(onRouteClick);
  const latest = useRef({ routes, stops });
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    clickRef.current = onRouteClick;
  }, [onRouteClick]);

  useEffect(() => {
    latest.current = { routes, stops };
  }, [routes, stops]);

  useEffect(() => {
    if (!MAP_KEY || !container.current) return;
    let cancelled = false;
    let map: MapLibreMap | null = null;
    let observer: MutationObserver | null = null;
    const markerMap = markers.current;

    import("maplibre-gl")
      .then((maplibregl) => {
        if (cancelled || !container.current) return;
        maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
        const created = new maplibregl.Map({
          container: container.current,
          style: styleUrl(prefersDark()),
          center: [75.9, 19.0],
          zoom: 5.4,
          attributionControl: false,
          cooperativeGestures: false,
        });
        map = created;
        created.addControl(new maplibregl.AttributionControl({ compact: true }));
        created.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
        created.on("error", (event) => {
          // Style or tile failures (bad key, quota, offline) show the fallback message.
          if (!created.isStyleLoaded()) setFailed(true);
          console.warn("map error", event.error?.message);
        });
        let bound = false;
        const setup = () => {
          if (cancelled) return;
          const dark = prefersDark();
          created.addSource("routes", { type: "geojson", data: routeFeatures(latest.current.routes) });
          created.addSource("stops", { type: "geojson", data: stopFeatures(latest.current.stops) });
          created.addLayer({
            id: "routes-casing",
            type: "line",
            source: "routes",
            layout: { "line-cap": "round", "line-join": "round" },
            paint: {
              "line-color": dark ? "#0b0f1a" : "#ffffff",
              "line-width": ["case", ["get", "selected"], 9, 6],
              "line-opacity": ["case", ["get", "selected"], 0.95, 0.6],
            },
          });
          created.addLayer({
            id: "routes-other",
            type: "line",
            source: "routes",
            filter: ["!", ["get", "selected"]],
            layout: { "line-cap": "round", "line-join": "round" },
            paint: { "line-color": ["get", "color"], "line-width": 3, "line-opacity": 0.7 },
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
              "circle-radius": [
                "match",
                ["get", "kind"],
                "pass_through",
                4,
                ["match", ["get", "role"], "origin", 8, "destination", 8, 6.5],
              ],
              "circle-color": [
                "match",
                ["get", "kind"],
                "pass_through",
                "#9ca3af",
                "suggested",
                "#ffffff",
                [
                  "match",
                  ["get", "status"],
                  "completed",
                  "#6b7280",
                  "next",
                  "#16a34a",
                  "#4f46e5",
                ],
              ],
              "circle-stroke-width": 2.5,
              "circle-stroke-color": ["match", ["get", "kind"], "suggested", "#4f46e5", "#ffffff"],
            },
          });
          created.addLayer({
            id: "stops-label",
            type: "symbol",
            source: "stops",
            layout: {
              "text-field": ["get", "label"],
              "text-size": ["match", ["get", "kind"], "pass_through", 11, 12.5],
              "text-offset": [0, 1.1],
              "text-anchor": "top",
              "text-optional": true,
              "text-font": ["Noto Sans Bold"],
            },
            paint: {
              "text-color": dark
                ? ["match", ["get", "kind"], "pass_through", "#9ca3af", "#f3f4f6"]
                : ["match", ["get", "kind"], "pass_through", "#6b7280", "#1f2937"],
              "text-halo-color": dark ? "#0b0f1a" : "#ffffff",
              "text-halo-width": 1.6,
            },
          });
          if (!bound) {
            bound = true;
            created.on("click", "routes-selected", (event) => {
              const id = event.features?.[0]?.properties?.id;
              if (id) clickRef.current?.(String(id));
            });
            created.on("click", "routes-other", (event) => {
              const id = event.features?.[0]?.properties?.id;
              if (id) clickRef.current?.(String(id));
            });
            for (const layer of ["routes-selected", "routes-other"]) {
              created.on("mouseenter", layer, () => {
                if (clickRef.current) created.getCanvas().style.cursor = "pointer";
              });
              created.on("mouseleave", layer, () => {
                created.getCanvas().style.cursor = "";
              });
            }
          }
          mapRef.current = created;
          setReady(true);
        };
        created.on("style.load", setup);

        // Follow the light/dark switch: swapping the style re-runs `setup`.
        const applyTheme = () => created.setStyle(styleUrl(prefersDark()));
        observer = new MutationObserver(applyTheme);
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      })
      .catch(() => setFailed(true));

    return () => {
      cancelled = true;
      observer?.disconnect();
      markerMap.clear();
      mapRef.current = null;
      fitted.current = null;
      map?.remove();
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource("routes") as GeoJSONSource | undefined)?.setData(routeFeatures(routes));
    (map.getSource("stops") as GeoJSONSource | undefined)?.setData(stopFeatures(stops));
    const key = fitKey ?? "once";
    const bounds = boundsOf(routes, stops, bus);
    if (bounds && fitted.current !== key) {
      map.fitBounds(bounds, { padding: 56, maxZoom: 12, duration: fitted.current ? 600 : 0 });
      fitted.current = key;
    }
  }, [ready, routes, stops, bus, fitKey]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const all: FleetBus[] = [...fleet, ...(bus ? [{ id: "__bus", ...bus }] : [])];
    let disposed = false;
    import("maplibre-gl").then((maplibregl) => {
      const current = mapRef.current;
      if (disposed || !current) return;
      const seen = new Set<string>();
      for (const item of all) {
        seen.add(item.id);
        let marker = markers.current.get(item.id);
        if (!marker) {
          const element = document.createElement("div");
          element.setAttribute("role", "img");
          marker = new maplibregl.Marker({ element, anchor: "center" })
            .setLngLat([item.lng, item.lat])
            .addTo(current);
          markers.current.set(item.id, marker);
        }
        const element = marker.getElement();
        // classList, not className: MapLibre positions the marker through its own class.
        element.classList.add(styles.bus);
        element.classList.toggle(styles.busStale, Boolean(item.stale));
        element.style.setProperty("--bus", item.color ?? "#dc2626");
        element.setAttribute("aria-label", item.stale ? "Bus (location not live)" : "Bus");
        element.innerHTML = `<span class="${styles.busIcon}">${BUS_SVG}</span>${
          item.label ? `<span class="${styles.busLabel}"></span>` : ""
        }`;
        const labelNode = element.querySelector(`.${styles.busLabel}`);
        if (labelNode) labelNode.textContent = item.label ?? "";
        marker.setLngLat([item.lng, item.lat]);
      }
      for (const [id, marker] of markers.current) {
        if (!seen.has(id)) {
          marker.remove();
          markers.current.delete(id);
        }
      }
    });
    return () => {
      disposed = true;
    };
  }, [ready, bus, fleet]);

  if (!MAP_KEY || failed) {
    return (
      <div className={styles.fallback} style={{ height }} role="status">
        {MAP_KEY
          ? "The map could not be loaded right now. Journey details are still up to date."
          : "The map is unavailable because no map key is configured."}
      </div>
    );
  }
  return (
    <div className={styles.frame} style={{ height }}>
      <div ref={container} className={styles.map} aria-label={label} />
    </div>
  );
}
