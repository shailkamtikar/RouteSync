"use client";

import {
  ArrowRight,
  Bus as BusIcon,
  CalendarClock,
  CircleAlert,
  Plus,
  Radio,
  Route as RouteIcon,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import { EmptyState, RouteLabel, SkeletonRows, Stat } from "@/components/kit/bits";
import { PageHeader } from "@/components/kit/PageHeader";
import { StatusBadge } from "@/components/kit/StatusBadge";
import { RouteMap, type FleetBus } from "@/components/map/RouteMap";
import { authedGet } from "@/lib/api";
import { delayText, type Commitment } from "@/lib/eta";
import { ROUTE_COLORS, type MapRoute } from "@/lib/mapData";
import { formatDay } from "@/lib/time";
import { LIVE_STATUSES, TIME_ZONE, type Journey } from "@/lib/types";
import { usePolling } from "@/lib/usePolling";
import { useResource } from "@/lib/useResource";

import ui from "../ui.module.css";
import styles from "./overview.module.css";

type LiveView = {
  id: string;
  position: { lat: number; lng: number; at: string } | null;
  stale: boolean;
  progress: number;
  commitment?: Commitment;
  coordinates: [number, number][];
  nextStop: string | null;
};

type MonitorLite = {
  position: { lat: number; lng: number; at: string } | null;
  eta: {
    progress_pct: number;
    flags: Record<string, boolean>;
    commitment?: Commitment;
    next_stop: { name: string };
  } | null;
  route: { coordinates: [number, number][] } | null;
};

function greeting(date = new Date()): string {
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", { timeZone: TIME_ZONE, hour: "2-digit", hour12: false }).format(date),
  );
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export function OverviewPanel() {
  const journeys = useResource<Journey[]>("/api/v1/journeys");
  const me = useResource<{ operator_name: string }>("/api/v1/me");
  const [focus, setFocus] = useState<string | null>(null);
  const [now] = useState(() => Date.now());

  const all = useMemo(() => journeys.data ?? [], [journeys.data]);
  const live = useMemo(() => all.filter((j) => LIVE_STATUSES.includes(j.status)), [all]);
  const liveKey = live.map((j) => j.id).join(",");

  const loadLive = useCallback(async (): Promise<LiveView[]> => {
    const results = await Promise.allSettled(
      liveKey
        .split(",")
        .filter(Boolean)
        .map(async (id) => {
          const monitor = await authedGet<MonitorLite>(`/api/v1/journeys/${id}/monitor`);
          return {
            id,
            position: monitor.position,
            stale: monitor.eta?.flags.stale ?? false,
            progress: monitor.eta?.progress_pct ?? 0,
            commitment: monitor.eta?.commitment,
            coordinates: monitor.route?.coordinates ?? [],
            nextStop: monitor.eta?.next_stop?.name ?? null,
          } satisfies LiveView;
        }),
    );
    return results.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
  }, [liveKey]);
  const fleet = usePolling(loadLive, 10_000, liveKey.length > 0);

  const views = useMemo(() => new Map((fleet.data ?? []).map((v) => [v.id, v])), [fleet.data]);

  const routes: MapRoute[] = useMemo(
    () =>
      live.flatMap((journey, index) => {
        const view = views.get(journey.id);
        if (!view || view.coordinates.length < 2) return [];
        return [
          {
            id: journey.id,
            name: `${journey.origin_name} to ${journey.destination_name}`,
            coordinates: view.coordinates,
            color: ROUTE_COLORS[index % ROUTE_COLORS.length],
            selected: focus === null || focus === journey.id,
          },
        ];
      }),
    [live, views, focus],
  );
  const buses: FleetBus[] = useMemo(
    () =>
      live.flatMap((journey, index) => {
        const view = views.get(journey.id);
        if (!view?.position) return [];
        return [
          {
            id: journey.id,
            lng: view.position.lng,
            lat: view.position.lat,
            stale: view.stale,
            label: journey.bus_registration,
            color: ROUTE_COLORS[index % ROUTE_COLORS.length],
          },
        ];
      }),
    [live, views],
  );

  const stats = useMemo(() => {
    const todayKey = new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE }).format(new Date());
    const dayOf = (iso: string) => new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE }).format(new Date(iso));
    return {
      onRoad: all.filter((j) => j.status === "in_progress" || j.status === "disrupted").length,
      boarding: all.filter((j) => j.status === "boarding").length,
      soon: all.filter(
        (j) =>
          ["published", "ready"].includes(j.status) &&
          new Date(j.departure_at).getTime() - now < 24 * 3600_000 &&
          new Date(j.departure_at).getTime() > now - 3600_000,
      ).length,
      needsAction: all.filter((j) => ["draft", "awaiting_confirmation"].includes(j.status) || j.plan_needs_review).length,
      passengersToday: all
        .filter((j) => dayOf(j.departure_at) === todayKey && j.status !== "cancelled")
        .reduce((sum, j) => sum + j.booked_passengers, 0),
    };
  }, [all, now]);

  const upcoming = useMemo(
    () =>
      all
        .filter((j) => ["published", "ready", "awaiting_confirmation", "draft"].includes(j.status))
        .sort((a, b) => a.departure_at.localeCompare(b.departure_at))
        .slice(0, 7),
    [all],
  );
  const attention = useMemo(
    () =>
      all
        .filter((j) => ["draft", "awaiting_confirmation"].includes(j.status) || j.plan_needs_review)
        .sort((a, b) => a.departure_at.localeCompare(b.departure_at))
        .slice(0, 5),
    [all],
  );

  const operator = me.data?.operator_name;

  return (
    <div className={ui.stack}>
      <PageHeader
        title={operator ? `${greeting()}, ${operator}` : greeting()}
        subtitle="Everything on the road and everything about to leave, in one place."
        actions={
          <Link href="/dashboard/journeys?new=1" className={ui.button}>
            <Plus size={16} aria-hidden /> New journey
          </Link>
        }
      />

      {journeys.error && <p className={ui.error} role="alert">{journeys.error}</p>}
      {journeys.loading ? (
        <SkeletonRows rows={3} height={86} />
      ) : (
        <>
          <section className={styles.stats} aria-label="Today at a glance">
            <Stat icon={Radio} tone="ok" label="On the road" value={stats.onRoad} />
            <Stat icon={BusIcon} tone="violet" label="Boarding now" value={stats.boarding} />
            <Stat icon={CalendarClock} tone="info" label="Departing in 24 h" value={stats.soon} />
            <Stat icon={CircleAlert} tone="warn" label="Need your action" value={stats.needsAction} />
            <Stat icon={Users} tone="brand" label="Passengers today" value={stats.passengersToday} />
          </section>

          <div className={styles.split}>
            <section className={`${ui.card} ${styles.mapCard}`} aria-label="Network map">
              <div className={ui.spread}>
                <h2 className={ui.sectionTitle}>Live network</h2>
                <span className={ui.small}>
                  {live.length === 0 ? "No bus is on the road" : `${buses.length} of ${live.length} buses reporting`}
                </span>
              </div>
              <div className={styles.mapWrap}>
                <RouteMap
                  routes={routes}
                  fleet={buses}
                  height="100%"
                  label="Live network map"
                  fitKey={`${focus ?? "all"}|${routes.length}`}
                  onRouteClick={(id) => setFocus((current) => (current === id ? null : id))}
                />
              </div>
            </section>

            <section className={styles.liveList} aria-label="Live now">
              <h2 className={ui.sectionTitle}>Live now</h2>
              {live.length === 0 && (
                <EmptyState icon={RouteIcon} title="Quiet on the road">
                  Journeys appear here as soon as they start boarding.
                </EmptyState>
              )}
              {live.map((journey, index) => {
                const view = views.get(journey.id);
                const late = view?.commitment && view.commitment.status !== "on_time";
                return (
                  <article
                    key={journey.id}
                    className={`${styles.liveCard} ${focus === journey.id ? styles.liveCardFocus : ""}`}
                    style={{ ["--accent" as string]: ROUTE_COLORS[index % ROUTE_COLORS.length] }}
                  >
                    <button
                      type="button"
                      className={styles.liveFocus}
                      onClick={() => setFocus((current) => (current === journey.id ? null : journey.id))}
                      aria-pressed={focus === journey.id}
                      aria-label={`Show ${journey.origin_name} to ${journey.destination_name} on the map`}
                    />
                    <div className={ui.spread}>
                      <RouteLabel from={journey.origin_name} to={journey.destination_name} />
                      <StatusBadge status={journey.status} />
                    </div>
                    <div className={styles.meta}>
                      <span>{journey.bus_registration}</span>
                      <span>·</span>
                      <span>
                        {journey.booked_passengers}/{journey.bus_capacity} booked
                      </span>
                      {view?.nextStop && (
                        <>
                          <span>·</span>
                          <span>next {view.nextStop}</span>
                        </>
                      )}
                    </div>
                    <div className={styles.progress} aria-label={`${Math.round(view?.progress ?? 0)} percent of the way`}>
                      <span style={{ width: `${Math.min(100, Math.round(view?.progress ?? 0))}%` }} />
                    </div>
                    <div className={ui.spread}>
                      <span className={late ? styles.late : styles.onTime}>
                        {view?.commitment ? delayText(view.commitment) : "Waiting for position"}
                        {view?.stale && " · location not live"}
                      </span>
                      <Link href={`/dashboard/journeys/${journey.id}/monitor`} className={ui.link}>
                        Monitor <ArrowRight size={14} aria-hidden style={{ verticalAlign: "-2px" }} />
                      </Link>
                    </div>
                  </article>
                );
              })}
            </section>
          </div>

          <div className={styles.columns}>
            <section className={ui.card} aria-label="Next departures">
              <div className={ui.spread}>
                <h2 className={ui.sectionTitle}>Next departures</h2>
                <Link href="/dashboard/journeys" className={ui.link}>
                  All journeys
                </Link>
              </div>
              {upcoming.length === 0 ? (
                <p className={ui.muted} style={{ marginTop: 12 }}>
                  Nothing scheduled. Create a journey to get started.
                </p>
              ) : (
                <ul className={styles.rows}>
                  {upcoming.map((journey) => (
                    <li key={journey.id}>
                      <Link href={`/dashboard/journeys/${journey.id}`} className={styles.row}>
                        <span className={styles.when}>{formatDay(journey.departure_at, journey.timezone)}</span>
                        <span className={styles.what}>
                          <RouteLabel from={journey.origin_name} to={journey.destination_name} />
                          <small>
                            {journey.bus_registration} · {journey.booked_passengers}/{journey.bus_capacity} booked
                          </small>
                        </span>
                        <StatusBadge status={journey.status} />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className={ui.card} aria-label="Needs your attention">
              <h2 className={ui.sectionTitle}>Needs your attention</h2>
              {attention.length === 0 ? (
                <p className={ui.muted} style={{ marginTop: 12 }}>
                  Every journey is confirmed. Nothing to do right now.
                </p>
              ) : (
                <ul className={styles.rows}>
                  {attention.map((journey) => (
                    <li key={journey.id}>
                      <Link href={`/dashboard/journeys/${journey.id}`} className={styles.row}>
                        <span className={styles.what}>
                          <RouteLabel from={journey.origin_name} to={journey.destination_name} />
                          <small>
                            {journey.plan_needs_review
                              ? "Bookings changed: review the stop plan"
                              : journey.status === "draft"
                                ? "Choose a route and confirm stops"
                                : "Plan submitted: assign the route"}
                            {" · "}
                            {formatDay(journey.departure_at, journey.timezone)}
                          </small>
                        </span>
                        <ArrowRight size={16} aria-hidden />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
