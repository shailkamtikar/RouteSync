"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { authedGet, authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { ageText, countdown, delayText, kilometres, type EtaSnapshot } from "@/lib/eta";
import type { MapRoute, MapStop } from "@/lib/mapData";
import { formatClock, formatInZone } from "@/lib/time";
import { usePolling } from "@/lib/usePolling";
import { useResource } from "@/lib/useResource";

import { RouteMap } from "./map/RouteMap";
import ui from "./ui.module.css";

type MonitorStop = {
  journey_stop_id: string;
  name: string;
  role: string;
  status: "pending" | "arrived" | "departed";
  pickup_count: number;
  drop_count: number;
  lng: number;
  lat: number;
};
type Alert = { id: string; type: string; severity: string; message: string; is_public: boolean };
type DecisionRow = {
  id: number;
  decided_at: string;
  outcome: string;
  reason: string;
  chosen_name: string | null;
};
type Monitor = {
  journey: {
    id: string;
    status: string;
    origin_name: string;
    destination_name: string;
    bus_registration: string;
    timezone: string;
    booking_eta_at: string;
    manual_mode: boolean;
    route_template_id: string | null;
  };
  position: { lat: number; lng: number; at: string } | null;
  eta: EtaSnapshot | null;
  route: { version: number; reason: string; coordinates: [number, number][] } | null;
  stops: MonitorStop[];
  alerts: Alert[];
  onboard: { method: string; onboard: number | null; planned_onboard: number };
  decisions: DecisionRow[];
};
type Incident = { id: string; kind: string; from_km: number; to_km: number; multiplier: number };

const RUNNING = ["boarding", "in_progress", "disrupted"];
const POLL_MS = 5000;

export function MonitorPanel({ journeyId }: { journeyId: string }) {
  const base = `/api/v1/journeys/${journeyId}`;
  const load = useCallback(() => authedGet<Monitor>(`${base}/monitor`), [base]);
  const { data, error: pollError, refresh } = usePolling(load, POLL_MS);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 15_000);
    return () => clearInterval(timer);
  }, []);

  const templateId = data?.journey.route_template_id ?? null;
  const incidentList = useResource<Incident[]>(
    templateId ? `/api/v1/route-templates/${templateId}/traffic-incidents` : null,
  );
  const incidents = incidentList.data ?? [];
  const loadIncidents = incidentList.reload;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      refresh();
    } catch (reason) {
      setError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  const stopEvent = (stop: MonitorStop, type: string, count = 0) =>
    run(() =>
      authedRequest(`${base}/stop-events`, "POST", {
        journey_stop_id: stop.journey_stop_id,
        type,
        count,
        client_event_id: crypto.randomUUID(),
      }),
    );

  function onCount(event: FormEvent<HTMLFormElement>, stop: MonitorStop) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const count = Number(data.get("count"));
    const type = String((event.nativeEvent as SubmitEvent).submitter?.getAttribute("value"));
    void stopEvent(stop, type, count).then(() => form.reset());
  }

  function onIncident(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    void run(async () => {
      await authedRequest(`/api/v1/route-templates/${templateId}/traffic-incidents`, "POST", {
        kind: values.get("kind"),
        from_km: Number(values.get("from_km")),
        to_km: Number(values.get("to_km")),
        multiplier: Number(values.get("multiplier") || 2),
      });
      form.reset();
      loadIncidents();
    });
  }

  const eta = data?.eta ?? null;
  const zone = data?.journey.timezone ?? "Asia/Kolkata";
  const stale = eta?.flags.stale ?? false;
  const statusByName = useMemo(
    () => new Map((eta?.stops ?? []).map((stop) => [stop.name, stop.status])),
    [eta],
  );
  const routeData = data?.route ?? null;
  const stopRows = data?.stops;
  const position = data?.position ?? null;
  const mapRoutes: MapRoute[] = useMemo(
    () =>
      routeData
        ? [{ id: `v${routeData.version}`, name: "Route", coordinates: routeData.coordinates }]
        : [],
    [routeData],
  );
  const mapStops: MapStop[] = useMemo(
    () =>
      (stopRows ?? []).map((stop) => {
        const status = statusByName.get(stop.name);
        return {
          id: stop.journey_stop_id,
          name: stop.name,
          lng: stop.lng,
          lat: stop.lat,
          kind: "active" as const,
          status: status === "completed" ? "completed" : status === "upcoming" ? "upcoming" : "next",
        };
      }),
    [stopRows, statusByName],
  );
  const bus = useMemo(
    () => (position ? { lng: position.lng, lat: position.lat, stale } : null),
    [position, stale],
  );

  if (!data) {
    return pollError ? (
      <div className={ui.stack}>
        <p className={ui.error} role="alert">
          {pollError === "Journey not found" ? "Journey not found." : pollError}
        </p>
        <Link href="/dashboard/journeys">Back to journeys</Link>
      </div>
    ) : (
      <p className={ui.muted}>Loading monitor…</p>
    );
  }

  const running = RUNNING.includes(data.journey.status);
  return (
    <div className={ui.stack}>
      <h1>
        {data.journey.origin_name} → {data.journey.destination_name}{" "}
        <span className={ui.badge} data-testid="monitor-status">
          {data.journey.status.replaceAll("_", " ")}
        </span>
      </h1>
      <p className={ui.muted}>
        Bus {data.journey.bus_registration} · <Link href={`/dashboard/journeys/${journeyId}`}>Journey setup</Link>
      </p>

      {pollError && (
        <p className={ui.error} role="status" data-testid="monitor-reconnecting">
          Reconnecting… showing the last update received.
        </p>
      )}
      {stale && (
        <p className={ui.error} role="status" data-testid="stale-banner">
          Location not live. Last position received {ageText(eta?.gps_age_s ?? null)}.
        </p>
      )}
      {error && (
        <p className={ui.error} data-testid="monitor-error">
          {error}
        </p>
      )}

      {data.alerts.length > 0 && (
        <ul className={ui.card} aria-label="Alerts" data-testid="monitor-alerts">
          {data.alerts.map((alert) => (
            <li key={alert.id} className={alert.severity === "info" ? ui.muted : ui.error}>
              {alert.message}
            </li>
          ))}
        </ul>
      )}

      {eta ? (
        <div className={ui.row}>
          <div className={ui.card} data-testid="next-stop-card">
            <div className={ui.muted}>{eta.flags.next_is_destination ? "Next: destination" : "Next stop"}</div>
            <strong>{eta.next_stop.name}</strong>
            <div>
              {countdown(eta.next_stop.eta, nowMs)} · {eta.next_stop.eta ? formatClock(eta.next_stop.eta, zone) : "—"}
            </div>
            <div className={ui.muted}>{kilometres(eta.next_stop.remaining_m)} to go</div>
          </div>
          <div className={ui.card} data-testid="destination-card">
            <div className={ui.muted}>Destination</div>
            <strong>{eta.destination.name}</strong>
            <div>
              {countdown(eta.destination.eta, nowMs)} · {eta.destination.eta ? formatClock(eta.destination.eta, zone) : "—"}
            </div>
            <div className={ui.muted}>{kilometres(eta.remaining_distance_m)} to go</div>
          </div>
          <div className={ui.card} data-testid="commitment-card">
            <div className={ui.muted}>Promised at booking</div>
            <strong>{formatInZone(data.journey.booking_eta_at, zone)}</strong>
            <div>{delayText(eta.commitment)}</div>
            <div className={ui.muted}>{eta.progress_pct.toFixed(0)}% of the route covered</div>
          </div>
          <div className={ui.card} data-testid="onboard-card">
            <div className={ui.muted}>On board</div>
            <strong>
              {data.onboard.method === "recorded_events" ? data.onboard.onboard : `${data.onboard.planned_onboard} (planned)`}
            </strong>
            <div className={ui.muted}>
              {data.onboard.method === "recorded_events" ? "from recorded boardings" : "no boardings recorded yet"}
            </div>
          </div>
        </div>
      ) : (
        <p className={ui.muted}>No route has been assigned to this journey yet.</p>
      )}

      <RouteMap key={data.route?.version ?? 0} routes={mapRoutes} stops={mapStops} bus={bus} />

      <section className={ui.stack} aria-label="Stops">
        <h2>Stops</h2>
        <div className={ui.tableWrap}>
          <table className={ui.table} aria-label="Stop events">
            <thead>
              <tr>
                <th>Stop</th>
                <th>Plan</th>
                <th>Status</th>
                <th>Record</th>
              </tr>
            </thead>
            <tbody>
              {data.stops.map((stop) => (
                <tr key={stop.journey_stop_id}>
                  <td>{stop.name}</td>
                  <td>
                    {stop.pickup_count} board, {stop.drop_count} alight
                  </td>
                  <td>
                    <span className={ui.badge}>{stop.status}</span>
                  </td>
                  <td>
                    {running && stop.status === "pending" && (
                      <button className={ui.buttonGhost} type="button" disabled={busy} onClick={() => stopEvent(stop, "arrived")}>
                        Arrived
                      </button>
                    )}
                    {running && stop.status === "arrived" && (
                      <form className={ui.row} onSubmit={(event) => onCount(event, stop)}>
                        <label className={ui.field}>
                          <input name="count" type="number" min={1} max={100} defaultValue={1} style={{ width: 64 }} aria-label={`Passenger count at ${stop.name}`} />
                        </label>
                        <button className={ui.buttonGhost} type="submit" value="boarded" disabled={busy}>
                          Boarded
                        </button>
                        <button className={ui.buttonGhost} type="submit" value="alighted" disabled={busy}>
                          Alighted
                        </button>
                        <button className={ui.button} type="button" disabled={busy} onClick={() => stopEvent(stop, "departed")}>
                          {stop.role === "destination" ? "Finish journey" : "Departed"}
                        </button>
                      </form>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className={ui.stack} aria-label="Route control">
        <h2>Route control</h2>
        <div className={ui.row}>
          <label className={ui.row}>
            <input
              type="checkbox"
              checked={data.journey.manual_mode}
              disabled={busy}
              onChange={(event) => run(() => authedRequest(`${base}/manual-mode`, "PUT", { enabled: event.target.checked }))}
            />
            Manual mode (route changes need my approval)
          </label>
          {running && (
            <>
              <button className={ui.buttonGhost} type="button" disabled={busy} onClick={() => run(() => authedRequest(`${base}/reroute/evaluate`, "POST", {}))}>
                Check for a better route
              </button>
              <button className={ui.buttonGhost} type="button" disabled={busy} onClick={() => run(() => authedRequest(`${base}/reroute/evaluate`, "POST", { apply: true }))}>
                Apply suggested change
              </button>
            </>
          )}
        </div>
        {data.route && (
          <p className={ui.muted} data-testid="route-version">
            Route version {data.route.version}: {data.route.reason}
          </p>
        )}
        {data.decisions.length > 0 && (
          <ul aria-label="Route decisions" data-testid="decision-log">
            {data.decisions.map((decision) => (
              <li key={decision.id}>
                {formatClock(decision.decided_at, zone)} · <strong>{decision.outcome.replaceAll("_", " ")}</strong> · {decision.reason}
              </li>
            ))}
          </ul>
        )}
      </section>

      {templateId && (
        <section className={ui.stack} aria-label="Simulated traffic">
          <h2>Simulated traffic</h2>
          <p className={ui.muted}>
            The map data has no live traffic. Incidents added here are simulated and labelled as such everywhere.
          </p>
          <form className={`${ui.row} ${ui.card}`} onSubmit={onIncident} aria-label="Add simulated incident">
            <label className={ui.field}>
              Type
              <select name="kind" defaultValue="slow">
                <option value="slow">Slow traffic</option>
                <option value="closure">Road closure</option>
              </select>
            </label>
            <label className={ui.field}>
              From km
              <input name="from_km" type="number" min={0} step="any" required style={{ width: 90 }} />
            </label>
            <label className={ui.field}>
              To km
              <input name="to_km" type="number" min={0} step="any" required style={{ width: 90 }} />
            </label>
            <label className={ui.field}>
              Times slower
              <input name="multiplier" type="number" min={1} max={20} step="any" defaultValue={3} style={{ width: 90 }} />
            </label>
            <button className={ui.button} type="submit" disabled={busy}>
              Add incident
            </button>
          </form>
          {incidents.length > 0 && (
            <ul aria-label="Active incidents">
              {incidents.map((incident) => (
                <li key={incident.id} className={ui.row}>
                  Simulated {incident.kind === "closure" ? "closure" : `slowdown ×${incident.multiplier}`}, km {incident.from_km}–{incident.to_km}
                  <button
                    className={ui.buttonDanger}
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        await authedRequest(`/api/v1/traffic-incidents/${incident.id}`, "DELETE");
                        loadIncidents();
                      })
                    }
                  >
                    End
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section className={ui.stack} aria-label="GPS device">
        <h2>GPS device</h2>
        <div className={ui.row}>
          <button
            className={ui.buttonGhost}
            type="button"
            disabled={busy}
            onClick={() =>
              run(async () => {
                const result = await authedRequest<{ token: string }>(`${base}/ingest-token`, "POST");
                setToken(result.token);
              })
            }
          >
            Create device token
          </button>
          <span className={ui.muted}>Creating a new token cancels the previous one.</span>
        </div>
        {token && (
          <p className={ui.card} data-testid="device-token">
            Copy this token now; it is shown only once: <code>{token}</code>
          </p>
        )}
      </section>
    </div>
  );
}
