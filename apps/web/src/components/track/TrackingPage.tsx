"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ageText, countdown, delayText, kilometres } from "@/lib/eta";
import type { MapRoute, MapStop } from "@/lib/mapData";
import { fetchPublicView, linkProblem, type PublicView } from "@/lib/publicTrack";
import { formatClock, formatDuration, formatInZone } from "@/lib/time";
import { usePolling } from "@/lib/usePolling";

import { RouteMap } from "../map/RouteMap";
import { CompanionPanel } from "./CompanionPanel";
import styles from "./tracking.module.css";

const POLL_MS = 10_000;

const STATUS_TEXT: Record<PublicView["journey"]["status"], string> = {
  not_started: "Not started yet",
  boarding: "Boarding",
  in_progress: "On the way",
  completed: "Journey completed",
  cancelled: "Journey cancelled",
};

function EtaCard({
  label,
  name,
  eta,
  remainingM,
  nowMs,
  zone,
  testId,
}: {
  label: string;
  name: string;
  eta: string | null;
  remainingM: number | null;
  nowMs: number;
  zone: string;
  testId: string;
}) {
  return (
    <div className={styles.card} data-testid={testId}>
      <div className={styles.cardLabel}>{label}</div>
      <div className={styles.cardName}>{name}</div>
      <div className={styles.cardBig}>{countdown(eta, nowMs)}</div>
      <div className={styles.cardMeta}>
        {eta ? `Expected ${formatClock(eta, zone)}` : "Time not available"}
        {remainingM !== null && ` · ${kilometres(remainingM)} to go`}
      </div>
    </div>
  );
}

export function TrackingPage({ token }: { token: string }) {
  const load = useCallback(() => fetchPublicView(token), [token]);
  const [problem, setProblem] = useState<"gone" | "unknown" | null>(null);
  const loadOrClassify = useCallback(async () => {
    try {
      return await load();
    } catch (error) {
      const kind = linkProblem(error);
      if (kind !== "unavailable") setProblem(kind);
      throw error;
    }
  }, [load]);
  const { data, error, updatedAt } = usePolling(loadOrClassify, POLL_MS, problem === null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 15_000);
    return () => clearInterval(timer);
  }, []);

  const routeData = data?.route ?? null;
  const stopRows = data?.stops;
  const passThrough = data?.pass_through;
  const busData = data?.bus ?? null;
  const mapRoutes: MapRoute[] = useMemo(
    () => (routeData ? [{ id: `v${routeData.version}`, name: "Route", coordinates: routeData.coordinates }] : []),
    [routeData],
  );
  const mapStops: MapStop[] = useMemo(
    () => [
      ...(stopRows ?? []).map((stop, index) => ({
        id: `s${index}`,
        name: stop.name,
        lng: stop.lng,
        lat: stop.lat,
        kind: "active" as const,
        status:
          stop.status === "completed" ? ("completed" as const) : stop.status === "upcoming" ? ("upcoming" as const) : ("next" as const),
      })),
      ...(passThrough ?? []).map((place, index) => ({
        id: `p${index}`,
        name: place.name,
        lng: place.lng,
        lat: place.lat,
        kind: "pass_through" as const,
      })),
    ],
    [stopRows, passThrough],
  );
  const bus = useMemo(
    () => (busData ? { lng: busData.lng, lat: busData.lat, stale: busData.stale } : null),
    [busData],
  );

  if (problem) {
    return (
      <main className={styles.page}>
        <div className={styles.unavailable} role="alert" data-testid="link-unavailable">
          <h1>Tracking unavailable</h1>
          <p>
            {problem === "gone"
              ? "This tracking link is no longer active. Please ask the operator for a new link."
              : "This tracking link was not recognised. Check the link you were given."}
          </p>
        </div>
      </main>
    );
  }
  if (!data) {
    return (
      <main className={styles.page}>
        <p className={styles.muted} role="status">
          {error ? "Live tracking is temporarily unavailable. Retrying…" : "Loading your journey…"}
        </p>
      </main>
    );
  }

  const { journey, eta } = data;
  const zone = journey.timezone;
  const finished = journey.status === "completed" || journey.status === "cancelled";
  const notStarted = journey.status === "not_started";
  const elapsed = Math.max(0, (nowMs - Date.parse(journey.departure_at)) / 1000);
  const staleOrMissing = !data.bus || data.bus.stale;
  const destinationStop = data.stops.find((stop) => stop.role === "destination");
  const destinationDone = finished || destinationStop?.status === "completed";

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div className={styles.route}>
          {journey.origin_name} → {journey.destination_name}
        </div>
        <div className={styles.status} data-testid="journey-status">
          {STATUS_TEXT[journey.status]}
          {updatedAt && !error && <span className={styles.muted}> · updated {ageText((nowMs - updatedAt) / 1000)}</span>}
        </div>
      </header>

      {error && (
        <p className={styles.notice} role="status" data-testid="reconnecting">
          Connection lost. Showing the last update received.
        </p>
      )}
      {!finished && !notStarted && staleOrMissing && (
        <p className={styles.warning} role="status" data-testid="stale-banner">
          {data.bus
            ? `Location not live. The last position was received ${ageText(eta?.gps_age_s ?? null)}.`
            : "No live position has been received yet. Times are based on the plan."}
        </p>
      )}
      {notStarted && (
        <p className={styles.notice} role="status">
          Departure planned for {formatInZone(journey.departure_at, zone)}. Times below are based on the plan.
        </p>
      )}
      {data.alerts.map((alert) => (
        <p key={alert.type} className={alert.severity === "critical" ? styles.warning : styles.notice} data-testid={`alert-${alert.type}`}>
          {alert.message}
        </p>
      ))}

      {eta && !finished && (
        <section className={styles.cards} aria-label="Arrival times">
          <EtaCard
            label={eta.flags.next_is_destination ? "Next: final destination" : "Next passenger stop"}
            name={eta.next_stop.name}
            eta={eta.next_stop.eta}
            remainingM={eta.next_stop.remaining_m}
            nowMs={nowMs}
            zone={zone}
            testId="next-stop-card"
          />
          <EtaCard
            label="Final destination"
            name={eta.destination.name}
            eta={eta.destination.eta}
            remainingM={eta.remaining_distance_m}
            nowMs={nowMs}
            zone={zone}
            testId="destination-card"
          />
        </section>
      )}
      {finished && (
        <section className={styles.card} data-testid="finished-card">
          <div className={styles.cardName}>{STATUS_TEXT[journey.status]}</div>
          {journey.status === "completed" && <div className={styles.cardMeta}>Thank you for travelling with us.</div>}
        </section>
      )}

      {eta?.commitment && !finished && (
        <section className={styles.promise} data-testid="promise">
          <div>
            <span className={styles.muted}>Arrival promised at booking</span>
            <strong> {formatInZone(eta.commitment.original_eta, zone)}</strong>
          </div>
          <div>
            <span className={styles.muted}>Now expected</span>
            <strong> {formatInZone(eta.commitment.predicted_eta, zone)}</strong>
            <span className={eta.commitment.status === "on_time" ? styles.ok : styles.late}> · {delayText(eta.commitment)}</span>
          </div>
        </section>
      )}

      <RouteMap key={routeData?.version ?? 0} routes={mapRoutes} stops={mapStops} bus={bus} height={320} />

      {eta && (
        <section className={styles.progress} aria-label="Progress" data-testid="progress">
          <div className={styles.bar}>
            <div className={styles.fill} style={{ width: `${Math.min(100, Math.max(0, eta.progress_pct))}%` }} />
          </div>
          <div className={styles.progressRow}>
            <span>{kilometres(eta.travelled_distance_m)} travelled</span>
            <span>{notStarted ? "" : `${formatDuration(elapsed)} elapsed`}</span>
            <span>{kilometres(eta.remaining_distance_m)} remaining</span>
          </div>
        </section>
      )}

      <section aria-label="Stops" className={styles.timeline}>
        <h2>Stops on this journey</h2>
        <ol className={styles.list} data-testid="timeline">
          {data.stops.filter((stop) => stop.role !== "destination").map((stop) => (
            <li key={stop.name} className={`${styles.item} ${styles[stop.status]}`} data-status={stop.status}>
              <span className={styles.dot} aria-hidden="true" />
              <div>
                <div className={styles.stopName}>
                  {stop.name}
                  {stop.status === "next" && <span className={styles.tag}>next</span>}
                  {stop.status === "current" && <span className={styles.tag}>here now</span>}
                  {stop.status === "completed" && <span className={styles.tagDone}>done</span>}
                </div>
                <div className={styles.cardMeta}>
                  {stop.status === "completed"
                    ? "Completed"
                    : stop.eta
                      ? `Expected ${formatClock(stop.eta, zone)} · ${countdown(stop.eta, nowMs)}`
                      : "Time not available"}
                  {data.counts_enabled && stop.boarding_count !== undefined && (
                    <> · {stop.boarding_count} boarding, {stop.alighting_count} alighting</>
                  )}
                </div>
              </div>
            </li>
          ))}
          <li
            className={`${styles.item} ${styles.destinationItem} ${destinationDone ? styles.completed : ""}`}
            data-status="destination"
          >
            <span className={styles.dot} aria-hidden="true" />
            <div>
              <div className={styles.stopName}>
                {journey.destination_name}
                {destinationDone && <span className={styles.tagDone}>done</span>}
              </div>
              <div className={styles.cardMeta}>
                {finished
                  ? STATUS_TEXT[journey.status]
                  : eta?.destination.eta
                    ? `Expected ${formatClock(eta.destination.eta, zone)}`
                    : "Time not available"}
                {data.counts_enabled && destinationStop?.alighting_count !== undefined && (
                  <> · {destinationStop.alighting_count} alighting</>
                )}
              </div>
            </div>
          </li>
        </ol>
        {data.pass_through.length > 0 && (
          <p className={styles.muted} data-testid="pass-through-note">
            Also on the road, with no passenger stop: {data.pass_through.map((p) => p.name).join(", ")}.
          </p>
        )}
        {data.counts_enabled && data.onboard && (
          <p className={styles.muted} data-testid="onboard-note">
            {data.onboard.method === "recorded_events"
              ? `${data.onboard.onboard} passengers on board (recorded).`
              : "Passenger counts above are planned figures."}
          </p>
        )}
      </section>

      <CompanionPanel token={token} view={data} />

      <footer className={styles.footer}>
        Times are estimates and may change. Map data © OpenStreetMap contributors.
      </footer>
    </main>
  );
}
