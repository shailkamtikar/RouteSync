"use client";

import { useMemo, useState, type FormEvent } from "react";

import { ApiError, authedGet, authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { ROUTE_COLORS, type MapRoute, type MapStop } from "@/lib/mapData";
import { formatDuration } from "@/lib/time";
import { useResource } from "@/lib/useResource";

import { RouteMap } from "./map/RouteMap";
import type { Service } from "./ServicesPanel";
import ui from "./ui.module.css";

type LatLng = { lat: number; lng: number };
export type RouteTemplate = {
  id: string;
  name: string;
  version: number;
  status: string;
  distance_m: number | null;
  duration_s: number | null;
  attribution: string | null;
  coordinates: [number, number][];
  stop_count: number;
};
export type RouteStop = {
  id: string;
  name: string;
  location: LatLng;
  chainage_m: number | null;
  kind: "passenger_stop" | "pass_through";
  role: "origin" | "intermediate" | "destination";
  source: string;
};
type Candidate = { name: string; location: LatLng; place_type: string; chainage_m: number };
type Candidates = { available: boolean; message: string | null; candidates: Candidate[] };
type WriteResult = { template: RouteTemplate; generation_error: string | null; warnings: string[] };

/** Parses lines like "Beed, 18.9891, 75.7601" into via-points. Throws a readable error. */
export function parseViaPoints(text: string) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const parts = line.split(",").map((part) => part.trim());
      const [lat, lng] = parts.slice(-2).map(Number);
      const name = parts.slice(0, -2).join(", ") || null;
      if (parts.length < 2 || !Number.isFinite(lat) || !Number.isFinite(lng)) {
        throw new Error(`Via-point line ${index + 1} must look like: Name, latitude, longitude`);
      }
      return { name, lat, lng };
    });
}

const km = (metres: number | null) => (metres === null ? "—" : `${(metres / 1000).toFixed(0)} km`);

export function RouteOptionsPanel({ serviceId }: { serviceId: string }) {
  const service = useResource<Service>(`/api/v1/services/${serviceId}`);
  const templates = useResource<RouteTemplate[]>(`/api/v1/services/${serviceId}/route-templates`);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected =
    templates.data?.find((template) => template.id === selectedId) ?? templates.data?.[0] ?? null;
  const stops = useResource<RouteStop[]>(
    selected ? `/api/v1/route-templates/${selected.id}/stops` : null,
  );
  const [candidates, setCandidates] = useState<Candidates | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const mapRoutes: MapRoute[] = useMemo(
    () =>
      (templates.data ?? []).map((template, index) => ({
        id: template.id,
        name: template.name,
        coordinates: template.coordinates,
        color: ROUTE_COLORS[index % ROUTE_COLORS.length],
        selected: template.id === selected?.id,
      })),
    [templates.data, selected?.id],
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

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (reason) {
      const local = reason instanceof Error && !(reason instanceof ApiError);
      setError(local ? reason.message : describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    void run(async () => {
      const result = await authedRequest<WriteResult>(
        `/api/v1/services/${serviceId}/route-templates`,
        "POST",
        {
          name: String(data.get("name") ?? ""),
          via_points: parseViaPoints(String(data.get("via_points") ?? "")),
        },
      );
      form.reset();
      setSelectedId(result.template.id);
      setCandidates(null);
      templates.reload();
      setNotice(
        result.generation_error
          ? `Saved, but the route could not be generated: ${result.generation_error}`
          : "Route option created.",
      );
    });
  }

  function addStop(name: string, location: LatLng, kind: RouteStop["kind"], source: string) {
    if (!selected) return;
    void run(async () => {
      await authedRequest(`/api/v1/route-templates/${selected.id}/stops`, "POST", {
        name,
        location,
        kind,
        source,
      });
      stops.reload();
      templates.reload();
      setCandidates((current) =>
        current
          ? { ...current, candidates: current.candidates.filter((item) => item.name !== name) }
          : current,
      );
    });
  }

  function onAddStop(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    addStop(
      String(data.get("name") ?? ""),
      { lat: Number(data.get("lat")), lng: Number(data.get("lng")) },
      data.get("kind") === "pass_through" ? "pass_through" : "passenger_stop",
      "operator",
    );
    form.reset();
  }

  const loadError = service.error ?? templates.error ?? stops.error;

  return (
    <div className={ui.stack}>
      <h1>
        {service.data ? `${service.data.origin_name} → ${service.data.destination_name}` : "Service"}
        : route options
      </h1>
      {service.data && (!service.data.origin_location || !service.data.destination_location) && (
        <p className={ui.error}>
          This service has no origin or destination coordinates, so routes cannot be generated.
        </p>
      )}

      <RouteMap key={selected?.id ?? "none"} routes={mapRoutes} stops={mapStops} />

      {(error ?? loadError) && (
        <p className={ui.error} data-testid="routes-error">
          {error ?? loadError}
        </p>
      )}
      {notice && (
        <p className={ui.muted} role="status" data-testid="routes-notice">
          {notice}
        </p>
      )}

      <form className={`${ui.stack} ${ui.card}`} onSubmit={onCreate} aria-label="New route option">
        <div className={ui.row}>
          <label className={ui.field}>
            Route option name
            <input name="name" required maxLength={120} placeholder="Via Ahmednagar and Beed" />
          </label>
          <button className={ui.button} type="submit" disabled={busy}>
            Create route option
          </button>
        </div>
        <label className={ui.field}>
          Via-points, in travel order (one per line: Name, latitude, longitude)
          <textarea name="via_points" rows={3} placeholder={"Ahmednagar, 19.0948, 74.7496\nBeed, 18.9891, 75.7601"} />
        </label>
      </form>

      {templates.data && templates.data.length === 0 && (
        <p className={ui.muted}>No route options yet.</p>
      )}
      {templates.data && templates.data.length > 0 && (
        <div className={ui.tableWrap}>
          <table className={ui.table} aria-label="Route options">
            <thead>
              <tr>
                <th>Route option</th>
                <th>Distance</th>
                <th>Drive time</th>
                <th>Stops</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {templates.data.map((template, index) => (
                <tr key={template.id} aria-selected={template.id === selected?.id}>
                  <td>
                    <span style={{ color: ROUTE_COLORS[index % ROUTE_COLORS.length] }}>●</span>{" "}
                    {template.name}
                    {template.version > 1 ? ` (v${template.version})` : ""}
                  </td>
                  <td>{km(template.distance_m)}</td>
                  <td>{template.duration_s === null ? "—" : formatDuration(template.duration_s)}</td>
                  <td>{template.stop_count}</td>
                  <td>
                    <span className={ui.badge}>{template.status}</span>
                  </td>
                  <td className={ui.row}>
                    <button
                      className={ui.buttonGhost}
                      type="button"
                      disabled={template.id === selected?.id}
                      onClick={() => {
                        setSelectedId(template.id);
                        setCandidates(null);
                      }}
                    >
                      {template.id === selected?.id ? "Showing" : "Show"}
                    </button>
                    {template.status === "unresolved" && (
                      <button
                        className={ui.buttonGhost}
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          run(async () => {
                            await authedRequest(`/api/v1/route-templates/${template.id}/generate`, "POST");
                            templates.reload();
                          })
                        }
                      >
                        Generate route
                      </button>
                    )}
                    <button
                      className={ui.buttonDanger}
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          await authedRequest(`/api/v1/route-templates/${template.id}`, "DELETE");
                          setSelectedId(null);
                          templates.reload();
                        })
                      }
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && selected.status === "ready" && (
        <section className={ui.stack} aria-label="Stops">
          <h2>Stops on “{selected.name}”</h2>
          <p className={ui.muted}>
            These stops belong to this route option only. A stop must lie on this route.
          </p>
          <div className={ui.tableWrap}>
            <table className={ui.table} aria-label="Route stops">
              <thead>
                <tr>
                  <th>Stop</th>
                  <th>Along route</th>
                  <th>Type</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {stops.data?.map((stop) => (
                  <tr key={stop.id}>
                    <td>{stop.name}</td>
                    <td>{km(stop.chainage_m)}</td>
                    <td>
                      {stop.role !== "intermediate"
                        ? stop.role
                        : stop.kind === "pass_through"
                          ? "No passenger stop"
                          : "Passenger stop"}
                    </td>
                    <td>
                      {stop.role === "intermediate" && (
                        <button
                          className={ui.buttonDanger}
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              await authedRequest(`/api/v1/route-template-stops/${stop.id}`, "DELETE");
                              stops.reload();
                              templates.reload();
                            })
                          }
                        >
                          Remove
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <form className={`${ui.row} ${ui.card}`} onSubmit={onAddStop} aria-label="Add stop">
            <label className={ui.field}>
              Stop name
              <input name="name" required maxLength={120} />
            </label>
            <label className={ui.field}>
              Latitude
              <input name="lat" type="number" step="any" min={-90} max={90} required />
            </label>
            <label className={ui.field}>
              Longitude
              <input name="lng" type="number" step="any" min={-180} max={180} required />
            </label>
            <label className={ui.field}>
              Type
              <select name="kind" defaultValue="passenger_stop">
                <option value="passenger_stop">Passenger stop</option>
                <option value="pass_through">No passenger stop (map label only)</option>
              </select>
            </label>
            <button className={ui.button} type="submit" disabled={busy}>
              Add stop
            </button>
          </form>

          <div className={ui.row}>
            <button
              className={ui.buttonGhost}
              type="button"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  setCandidates(
                    await authedGet<Candidates>(
                      `/api/v1/route-templates/${selected.id}/stop-candidates`,
                    ),
                  );
                })
              }
            >
              Suggest places from OpenStreetMap
            </button>
            <span className={ui.muted}>Suggestions become stops only when you add them.</span>
          </div>
          {candidates && !candidates.available && <p className={ui.muted}>{candidates.message}</p>}
          {candidates?.available && candidates.candidates.length === 0 && (
            <p className={ui.muted}>No further places found along this route.</p>
          )}
          {candidates?.available && candidates.candidates.length > 0 && (
            <div className={ui.tableWrap}>
              <table className={ui.table} aria-label="Suggested places">
                <thead>
                  <tr>
                    <th>Place</th>
                    <th>Along route</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {candidates.candidates.map((candidate) => (
                    <tr key={candidate.name}>
                      <td>
                        {candidate.name} <span className={ui.muted}>({candidate.place_type})</span>
                      </td>
                      <td>{km(candidate.chainage_m)}</td>
                      <td className={ui.row}>
                        <button
                          className={ui.buttonGhost}
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            addStop(candidate.name, candidate.location, "passenger_stop", "osm")
                          }
                        >
                          Add as passenger stop
                        </button>
                        <button
                          className={ui.buttonGhost}
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            addStop(candidate.name, candidate.location, "pass_through", "osm")
                          }
                        >
                          Mark as no passenger stop
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {selected.attribution && <p className={ui.muted}>Route data: {selected.attribution}</p>}
        </section>
      )}
    </div>
  );
}
