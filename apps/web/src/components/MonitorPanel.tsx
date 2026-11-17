"use client";

import {
  Bell,
  Check,
  CircleAlert,
  Clock,
  Flag,
  Gauge,
  MapPin,
  Radio,
  Route as RouteIcon,
  Users,
  WifiOff,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { authedGet, authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { ageText, countdown, delayText, kilometres, type EtaSnapshot } from "@/lib/eta";
import type { MapRoute, MapStop } from "@/lib/mapData";
import { formatClock, formatInZone } from "@/lib/time";
import { usePolling } from "@/lib/usePolling";
import { useResource } from "@/lib/useResource";

import { RouteLabel, SkeletonRows } from "./kit/bits";
import { PageHeader } from "./kit/PageHeader";
import { Pill, StatusBadge } from "./kit/StatusBadge";
import { RouteMap } from "./map/RouteMap";
import styles from "./monitor.module.css";
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
        <PageHeader title="Journey not found" back={{ href: "/dashboard/journeys", label: "Journeys" }} />
        <p className={ui.error} role="alert">
          {pollError === "Journey not found" ? "This journey does not exist or belongs to another operator." : pollError}
        </p>
      </div>
    ) : (
      <SkeletonRows rows={3} height={110} />
    );
  }

  const running = RUNNING.includes(data.journey.status);
  const nextEta = eta?.next_stop.eta ?? null;
  const destEta = eta?.destination.eta ?? null;
  const late = eta?.commitment && eta.commitment.status !== "on_time";

  return (
    <div className={ui.stack}>
      <PageHeader
        back={{ href: `/dashboard/journeys/${journeyId}`, label: "Journey setup" }}
        title={<RouteLabel from={data.journey.origin_name} to={data.journey.destination_name} />}
        subtitle={
          <span style={{ display: "inline-flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span data-testid="monitor-status" className={styles.statusText}>
              <StatusBadge status={data.journey.status} />
            </span>
            <span>Bus {data.journey.bus_registration}</span>
            {data.journey.manual_mode && <Pill tone="warn">Manual mode</Pill>}
          </span>
        }
        actions={
          <span className={styles.live} aria-live="polite">
            <Radio size={14} aria-hidden /> Updating every {POLL_MS / 1000} s
          </span>
        }
      />

      {pollError && (
        <p className={`${ui.notice} ${ui.noticeWarn}`} role="status" data-testid="monitor-reconnecting">
          <WifiOff size={16} aria-hidden /> Reconnecting… showing the last update received.
        </p>
      )}
      {stale && (
        <p className={`${ui.notice} ${ui.noticeWarn}`} role="status" data-testid="stale-banner">
          <CircleAlert size={16} aria-hidden /> Location not live. Last position received {ageText(eta?.gps_age_s ?? null)}.
        </p>
      )}
      {error && (
        <p className={ui.error} role="alert" data-testid="monitor-error">
          {error}
        </p>
      )}

      {data.alerts.length > 0 && (
        <ul className={styles.alerts} aria-label="Alerts" data-testid="monitor-alerts">
          {data.alerts.map((alert) => (
            <li key={alert.id} data-severity={alert.severity}>
              <Bell size={15} aria-hidden /> {alert.message}
            </li>
          ))}
        </ul>
      )}

      {eta ? (
        <div className={styles.kpis}>
          <div className={styles.kpi} data-testid="next-stop-card">
            <span className={styles.kpiLabel}>
              <MapPin size={14} aria-hidden /> {eta.flags.next_is_destination ? "Next: destination" : "Next stop"}
            </span>
            <strong className={styles.kpiBig}>{eta.next_stop.name}</strong>
            <span className={styles.kpiValue}>
              {countdown(nextEta, nowMs)}
              <small>{nextEta ? ` · ${formatClock(nextEta, zone)}` : ""}</small>
            </span>
            <span className={styles.kpiSub}>{kilometres(eta.next_stop.remaining_m)} to go</span>
          </div>
          <div className={styles.kpi} data-testid="destination-card">
            <span className={styles.kpiLabel}>
              <Flag size={14} aria-hidden /> Destination
            </span>
            <strong className={styles.kpiBig}>{eta.destination.name}</strong>
            <span className={styles.kpiValue}>
              {countdown(destEta, nowMs)}
              <small>{destEta ? ` · ${formatClock(destEta, zone)}` : ""}</small>
            </span>
            <span className={styles.kpiSub}>{kilometres(eta.remaining_distance_m)} to go</span>
          </div>
          <div className={`${styles.kpi} ${late ? styles.kpiLate : ""}`} data-testid="commitment-card">
            <span className={styles.kpiLabel}>
              <Clock size={14} aria-hidden /> Promised at booking
            </span>
            <strong className={styles.kpiBig}>{formatInZone(data.journey.booking_eta_at, zone)}</strong>
            <span className={`${styles.kpiValue} ${late ? styles.warnText : styles.okText}`}>{delayText(eta.commitment)}</span>
            <span className={styles.kpiSub}>{eta.progress_pct.toFixed(0)}% of the route covered</span>
          </div>
          <div className={styles.kpi} data-testid="onboard-card">
            <span className={styles.kpiLabel}>
              <Users size={14} aria-hidden /> On board
            </span>
            <strong className={styles.kpiBig}>
              {data.onboard.method === "recorded_events" ? data.onboard.onboard : `${data.onboard.planned_onboard} (planned)`}
            </strong>
            <span className={styles.kpiSub}>
              {data.onboard.method === "recorded_events" ? "from recorded boardings" : "no boardings recorded yet"}
            </span>
          </div>
        </div>
      ) : (
        <p className={ui.notice}>No route has been assigned to this journey yet.</p>
      )}

      <div className={styles.layout}>
        <div className={styles.mapCol}>
          <RouteMap key={data.route?.version ?? 0} routes={mapRoutes} stops={mapStops} bus={bus} height="100%" label="Live journey map" />
        </div>

        <div className={styles.side}>
          <section className={styles.panel} aria-label="Stops">
            <h2 className={ui.sectionTitle}>Stops</h2>
            <ol className={styles.stops} aria-label="Stop events">
              {data.stops.map((stop) => (
                <li key={stop.journey_stop_id} data-status={stop.status}>
                  <span className={styles.node} aria-hidden>
                    {stop.status === "departed" && <Check size={11} />}
                  </span>
                  <div className={styles.stopBody}>
                    <div className={ui.spread}>
                      <strong>{stop.name}</strong>
                      <Pill tone={stop.status === "departed" ? "neutral" : stop.status === "arrived" ? "ok" : "info"}>
                        {stop.status === "pending" ? "Upcoming" : stop.status === "arrived" ? "At stop" : "Departed"}
                      </Pill>
                    </div>
                    <small>
                      {stop.pickup_count} board · {stop.drop_count} alight
                    </small>
                    {running && stop.status === "pending" && (
                      <button className={`${ui.buttonGhost} ${ui.sm}`} type="button" disabled={busy} onClick={() => stopEvent(stop, "arrived")}>
                        Arrived
                      </button>
                    )}
                    {running && stop.status === "arrived" && (
                      <form className={styles.recordRow} onSubmit={(event) => onCount(event, stop)}>
                        <input
                          name="count"
                          type="number"
                          min={1}
                          max={100}
                          defaultValue={1}
                          aria-label={`Passenger count at ${stop.name}`}
                          className={ui.input}
                          style={{ width: 70 }}
                        />
                        <button className={`${ui.buttonGhost} ${ui.sm}`} type="submit" value="boarded" disabled={busy}>
                          Boarded
                        </button>
                        <button className={`${ui.buttonGhost} ${ui.sm}`} type="submit" value="alighted" disabled={busy}>
                          Alighted
                        </button>
                        <button className={`${ui.button} ${ui.sm}`} type="button" disabled={busy} onClick={() => stopEvent(stop, "departed")}>
                          {stop.role === "destination" ? "Finish journey" : "Departed"}
                        </button>
                      </form>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        </div>
      </div>

      <div className={styles.columns}>
        <section className={styles.panel} aria-label="Route control">
          <div className={ui.rowCenter}>
            <RouteIcon size={18} aria-hidden style={{ color: "var(--brand)" }} />
            <h2 className={ui.sectionTitle}>Route control</h2>
          </div>
          <label className={ui.checkboxRow}>
            <input
              type="checkbox"
              checked={data.journey.manual_mode}
              disabled={busy}
              onChange={(event) => run(() => authedRequest(`${base}/manual-mode`, "PUT", { enabled: event.target.checked }))}
            />
            Manual mode (route changes need my approval)
          </label>
          {running && (
            <div className={ui.rowCenter}>
              <button className={ui.buttonGhost} type="button" disabled={busy} onClick={() => run(() => authedRequest(`${base}/reroute/evaluate`, "POST", {}))}>
                <Gauge size={15} aria-hidden /> Check for a better route
              </button>
              <button className={ui.buttonSoft} type="button" disabled={busy} onClick={() => run(() => authedRequest(`${base}/reroute/evaluate`, "POST", { apply: true }))}>
                Apply suggested change
              </button>
            </div>
          )}
          {data.route && (
            <p className={ui.small} data-testid="route-version">
              Route version {data.route.version}: {data.route.reason}
            </p>
          )}
          {data.decisions.length > 0 && (
            <ul className={styles.decisions} aria-label="Route decisions" data-testid="decision-log">
              {data.decisions.map((decision) => (
                <li key={decision.id}>
                  <time>{formatClock(decision.decided_at, zone)}</time>
                  <span>
                    <strong>{decision.outcome.replaceAll("_", " ")}</strong> · {decision.reason}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {templateId && (
          <section className={styles.panel} aria-label="Simulated traffic">
            <h2 className={ui.sectionTitle}>Simulated traffic</h2>
            <p className={ui.small}>
              The map data has no live traffic. Incidents added here are simulated and labelled as such everywhere.
            </p>
            <form className={ui.row} onSubmit={onIncident} aria-label="Add simulated incident">
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
              <ul className={styles.incidents} aria-label="Active incidents">
                {incidents.map((incident) => (
                  <li key={incident.id}>
                    <span>
                      Simulated {incident.kind === "closure" ? "closure" : `slowdown ×${incident.multiplier}`}, km {incident.from_km}–{incident.to_km}
                    </span>
                    <button
                      className={`${ui.buttonDanger} ${ui.sm}`}
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

        <section className={styles.panel} aria-label="GPS device">
          <h2 className={ui.sectionTitle}>GPS device</h2>
          <p className={ui.small}>The bus reports its position with a private device token. Creating a new token cancels the previous one.</p>
          <div>
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
          </div>
          {token && (
            <p className={ui.notice} data-testid="device-token">
              Copy this token now; it is shown only once: <code className={ui.mono}>{token}</code>
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
