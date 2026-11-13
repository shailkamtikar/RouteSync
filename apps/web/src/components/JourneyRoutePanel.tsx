"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import type { MapRoute, MapStop } from "@/lib/mapData";
import { useResource } from "@/lib/useResource";

import type { Journey } from "./JourneysPanel";
import { RouteMap } from "./map/RouteMap";
import type { RouteStop, RouteTemplate } from "./RouteOptionsPanel";
import ui from "./ui.module.css";

/** Lets the operator choose which route option a draft journey follows. */
export function JourneyRoutePanel({ journey, onChanged }: { journey: Journey; onChanged: () => void }) {
  const templates = useResource<RouteTemplate[]>(
    `/api/v1/services/${journey.service_id}/route-templates?include_archived=true`,
  );
  const stops = useResource<RouteStop[]>(
    journey.route_template_id ? `/api/v1/route-templates/${journey.route_template_id}/stops` : null,
  );
  const [choice, setChoice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const current = templates.data?.find((template) => template.id === journey.route_template_id);
  const selectable = (templates.data ?? []).filter((template) => template.status === "ready");
  const isDraft = journey.status === "draft";

  const mapRoutes: MapRoute[] = useMemo(
    () =>
      current ? [{ id: current.id, name: current.name, coordinates: current.coordinates }] : [],
    [current],
  );
  const mapStops: MapStop[] = useMemo(
    () =>
      (stops.data ?? []).map((stop) => ({
        id: stop.id,
        name: stop.name,
        lng: stop.location.lng,
        lat: stop.location.lat,
        kind: stop.kind === "pass_through" ? "pass_through" : "suggested",
      })),
    [stops.data],
  );

  async function apply() {
    if (!choice) return;
    setBusy(true);
    setError(null);
    try {
      await authedRequest(`/api/v1/journeys/${journey.id}/route-template`, "PUT", {
        route_template_id: choice,
      });
      setChoice("");
      onChanged();
    } catch (reason) {
      setError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={ui.stack} aria-label="Route">
      <h2>Route</h2>
      <p data-testid="journey-route">
        {current ? (
          <>
            Following <strong>{current.name}</strong>
            {current.distance_m !== null && ` (${(current.distance_m / 1000).toFixed(0)} km)`}
          </>
        ) : (
          "No route option chosen yet."
        )}
      </p>
      {isDraft && (
        <div className={ui.row}>
          <label className={ui.field}>
            Route option
            <select value={choice} onChange={(event) => setChoice(event.target.value)}>
              <option value="">Choose…</option>
              {selectable
                .filter((template) => template.id !== journey.route_template_id)
                .map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.name}
                  </option>
                ))}
            </select>
          </label>
          <button className={ui.button} type="button" disabled={busy || !choice} onClick={apply}>
            Use this route
          </button>
          <Link href={`/dashboard/services/${journey.service_id}`}>Manage route options</Link>
        </div>
      )}
      {isDraft && journey.route_template_id && (
        <p className={ui.muted}>Changing the route option clears the confirmed stops.</p>
      )}
      {(error ?? templates.error) && (
        <p className={ui.error} data-testid="route-error">
          {error ?? templates.error}
        </p>
      )}
      {current && <RouteMap key={current.id} routes={mapRoutes} stops={mapStops} height={340} />}
    </section>
  );
}
