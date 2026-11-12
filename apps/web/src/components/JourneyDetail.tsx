"use client";

import Link from "next/link";

import { formatInZone } from "@/lib/time";
import { useResource } from "@/lib/useResource";

import { BookingsPanel } from "./BookingsPanel";
import type { Journey } from "./JourneysPanel";
import ui from "./ui.module.css";

const PRE_DEPARTURE = ["draft", "awaiting_confirmation", "ready", "published", "boarding"];

export function JourneyDetail({ journeyId }: { journeyId: string }) {
  const { data: journey, error, reload } = useResource<Journey>(`/api/v1/journeys/${journeyId}`);

  if (error) {
    return (
      <div className={ui.stack}>
        <p className={ui.error} role="alert">
          {error === "Journey not found" ? "Journey not found." : error}
        </p>
        <Link href="/dashboard/journeys">Back to journeys</Link>
      </div>
    );
  }
  if (!journey) return <p className={ui.muted}>Loading journey…</p>;

  return (
    <div className={ui.stack}>
      <h1>
        {journey.origin_name} → {journey.destination_name}
      </h1>
      <dl className={`${ui.row} ${ui.card}`} data-testid="journey-summary">
        <div className={ui.field}>
          <dt className={ui.muted}>Status</dt>
          <dd>
            <span className={ui.badge}>{journey.status.replaceAll("_", " ")}</span>
          </dd>
        </div>
        <div className={ui.field}>
          <dt className={ui.muted}>Bus</dt>
          <dd>{journey.bus_registration}</dd>
        </div>
        <div className={ui.field}>
          <dt className={ui.muted}>Departure</dt>
          <dd>{formatInZone(journey.departure_at, journey.timezone)}</dd>
        </div>
        <div className={ui.field}>
          <dt className={ui.muted}>Arrival promised at booking</dt>
          <dd>{formatInZone(journey.booking_eta_at, journey.timezone)}</dd>
        </div>
        <div className={ui.field}>
          <dt className={ui.muted}>Booked passengers</dt>
          <dd data-testid="booked-passengers">
            {journey.booked_passengers} / {journey.bus_capacity}
          </dd>
        </div>
      </dl>
      {journey.plan_needs_review && (
        <p className={ui.error} role="status">
          Bookings changed after the stop plan was confirmed. Review the stop plan.
        </p>
      )}
      <BookingsPanel
        journeyId={journey.id}
        editable={PRE_DEPARTURE.includes(journey.status)}
        onChanged={reload}
      />
    </div>
  );
}
