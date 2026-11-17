"use client";

import { Check } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { formatDay, formatInZone } from "@/lib/time";
import type { Journey } from "@/lib/types";
import { useResource } from "@/lib/useResource";

import { BookingsPanel } from "./BookingsPanel";
import { JourneyActions, nextHint, STEPS } from "./journeys/JourneyActions";
import { JourneyPlanPanel } from "./JourneyPlanPanel";
import { JourneyRoutePanel } from "./JourneyRoutePanel";
import { RouteLabel, SkeletonRows, Tabs } from "./kit/bits";
import { PageHeader } from "./kit/PageHeader";
import { StatusBadge } from "./kit/StatusBadge";
import { TrackingLinkPanel } from "./TrackingLinkPanel";
import ui from "./ui.module.css";
import styles from "./journeys/detail.module.css";

const PRE_DEPARTURE = ["draft", "awaiting_confirmation", "ready", "published", "boarding"];
type Tab = "plan" | "bookings" | "link";

export function JourneyDetail({ journeyId }: { journeyId: string }) {
  const { data: journey, error, reload } = useResource<Journey>(`/api/v1/journeys/${journeyId}`);
  const [tab, setTab] = useState<Tab>("plan");

  if (error) {
    return (
      <div className={ui.stack}>
        <PageHeader title="Journey not found" back={{ href: "/dashboard/journeys", label: "Journeys" }} />
        <p className={ui.error} role="alert">
          {error === "Journey not found" ? "This journey does not exist or belongs to another operator." : error}
        </p>
        <Link href="/dashboard/journeys" className={ui.link}>
          Back to journeys
        </Link>
      </div>
    );
  }
  if (!journey) return <SkeletonRows rows={3} height={110} />;

  const stepIndex = STEPS.findIndex((step) => step.id === (journey.status === "disrupted" ? "in_progress" : journey.status));
  const cancelled = journey.status === "cancelled";
  const hint = nextHint(journey.status);
  const fill = Math.min(100, Math.round((journey.booked_passengers / Math.max(1, journey.bus_capacity)) * 100));

  return (
    <div className={ui.stack}>
      <PageHeader
        back={{ href: "/dashboard/journeys", label: "Journeys" }}
        title={<RouteLabel from={journey.origin_name} to={journey.destination_name} />}
        subtitle={
          <span style={{ display: "inline-flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <StatusBadge status={journey.status} />
            <span>
              {journey.bus_registration} · departs {formatDay(journey.departure_at, journey.timezone)}
            </span>
          </span>
        }
        actions={<JourneyActions journey={journey} onChanged={reload} />}
      />

      {cancelled ? (
        <p className={ui.error} role="status">
          This journey was cancelled.
        </p>
      ) : (
        <section className={`${ui.card} ${styles.progressCard}`} aria-label="Journey progress">
          <ol className={styles.steps}>
            {STEPS.map((step, index) => {
              const state = index < stepIndex || journey.status === "completed" ? "done" : index === stepIndex ? "current" : "todo";
              return (
                <li key={step.id} data-state={state} data-disrupted={journey.status === "disrupted" && state === "current"}>
                  <span className={styles.stepDot}>{state === "done" ? <Check size={13} aria-hidden /> : index + 1}</span>
                  <span className={styles.stepLabel}>{step.label}</span>
                </li>
              );
            })}
          </ol>
          {hint && <p className={styles.hint}>{hint}</p>}
        </section>
      )}

      <section className={ui.card} aria-label="Summary">
        <dl className={styles.facts} data-testid="journey-summary">
          <div>
            <dt>Status</dt>
            <dd>
              <StatusBadge status={journey.status} />
            </dd>
          </div>
          <div>
            <dt>Bus</dt>
            <dd>{journey.bus_registration}</dd>
          </div>
          <div>
            <dt>Departure</dt>
            <dd>{formatInZone(journey.departure_at, journey.timezone)}</dd>
          </div>
          <div>
            <dt>Scheduled arrival</dt>
            <dd>{formatInZone(journey.scheduled_arrival_at, journey.timezone)}</dd>
          </div>
          <div>
            <dt>Arrival promised at booking</dt>
            <dd>{formatInZone(journey.booking_eta_at, journey.timezone)}</dd>
          </div>
          <div>
            <dt>Booked passengers</dt>
            <dd data-testid="booked-passengers">
              {journey.booked_passengers} / {journey.bus_capacity}
              <span className={styles.miniBar} aria-hidden>
                <span style={{ width: `${fill}%` }} />
              </span>
            </dd>
          </div>
        </dl>
      </section>

      {journey.plan_needs_review && (
        <p className={`${ui.notice} ${ui.noticeWarn}`} role="status">
          Bookings changed after the stop plan was confirmed. Review the stop plan before submitting.
        </p>
      )}

      <Tabs
        label="Journey sections"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "plan", label: "Route and stops" },
          { id: "bookings", label: "Bookings", count: journey.booked_passengers },
          { id: "link", label: "Passenger link" },
        ]}
      />
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className={ui.stack}>
        {tab === "plan" && (
          <>
            <JourneyRoutePanel journey={journey} onChanged={reload} />
            <JourneyPlanPanel journey={journey} onChanged={reload} />
          </>
        )}
        {tab === "bookings" && (
          <BookingsPanel
            journeyId={journey.id}
            routeTemplateId={journey.route_template_id}
            capacity={journey.bus_capacity}
            editable={PRE_DEPARTURE.includes(journey.status)}
            onChanged={reload}
          />
        )}
        {tab === "link" && <TrackingLinkPanel journey={journey} onChanged={reload} />}
      </div>
    </div>
  );
}
