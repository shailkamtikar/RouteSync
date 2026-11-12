"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatInZone, zonedInputToIso } from "@/lib/time";
import { useResource } from "@/lib/useResource";

import type { Bus } from "./BusesPanel";
import type { Service } from "./ServicesPanel";
import ui from "./ui.module.css";

export type Journey = {
  id: string;
  bus_id: string;
  bus_registration: string;
  bus_capacity: number;
  service_id: string;
  origin_name: string;
  destination_name: string;
  route_template_id: string | null;
  departure_at: string;
  scheduled_arrival_at: string;
  booking_eta_at: string;
  timezone: string;
  status: string;
  manual_mode: boolean;
  plan_needs_review: boolean;
  public_counts_enabled: boolean;
  booked_passengers: number;
};

const TIME_ZONE = "Asia/Kolkata";

export function JourneysPanel() {
  const journeys = useResource<Journey[]>("/api/v1/journeys");
  const buses = useResource<Bus[]>("/api/v1/buses");
  const services = useResource<Service[]>("/api/v1/services");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setError(null);
    try {
      await authedRequest("/api/v1/journeys", "POST", {
        bus_id: data.get("bus_id"),
        service_id: data.get("service_id"),
        departure_at: zonedInputToIso(String(data.get("departure_at")), TIME_ZONE),
        scheduled_arrival_at: zonedInputToIso(String(data.get("scheduled_arrival_at")), TIME_ZONE),
        timezone: TIME_ZONE,
      });
      form.reset();
      journeys.reload();
    } catch (reason) {
      setError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  const loadError = journeys.error ?? buses.error ?? services.error;
  const canCreate = (buses.data?.length ?? 0) > 0 && (services.data?.length ?? 0) > 0;

  return (
    <div className={ui.stack}>
      <form className={`${ui.row} ${ui.card}`} onSubmit={onCreate} aria-label="New journey">
        <label className={ui.field}>
          Service
          <select name="service_id" required defaultValue="">
            <option value="" disabled>
              Choose…
            </option>
            {services.data?.map((service) => (
              <option key={service.id} value={service.id}>
                {service.origin_name} → {service.destination_name}
              </option>
            ))}
          </select>
        </label>
        <label className={ui.field}>
          Bus
          <select name="bus_id" required defaultValue="">
            <option value="" disabled>
              Choose…
            </option>
            {buses.data?.map((bus) => (
              <option key={bus.id} value={bus.id}>
                {bus.registration} ({bus.capacity} seats)
              </option>
            ))}
          </select>
        </label>
        <label className={ui.field}>
          Departure (IST)
          <input name="departure_at" type="datetime-local" required />
        </label>
        <label className={ui.field}>
          Scheduled arrival (IST)
          <input name="scheduled_arrival_at" type="datetime-local" required />
        </label>
        <button className={ui.button} type="submit" disabled={busy || !canCreate}>
          Create journey
        </button>
      </form>
      {!canCreate && !buses.loading && !services.loading && (
        <p className={ui.muted}>Add at least one bus and one service before creating a journey.</p>
      )}

      {(error ?? loadError) && (
        <p className={ui.error} data-testid="panel-error">
          {error ?? loadError}
        </p>
      )}
      {journeys.loading && <p className={ui.muted}>Loading journeys…</p>}
      {journeys.data && journeys.data.length === 0 && <p className={ui.muted}>No journeys yet.</p>}

      {journeys.data && journeys.data.length > 0 && (
        <div className={ui.tableWrap}>
          <table className={ui.table}>
            <thead>
              <tr>
                <th>Service</th>
                <th>Bus</th>
                <th>Departure</th>
                <th>Scheduled arrival</th>
                <th>Passengers</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {journeys.data.map((journey) => (
                <tr key={journey.id}>
                  <td>
                    {journey.origin_name} → {journey.destination_name}
                  </td>
                  <td>{journey.bus_registration}</td>
                  <td>{formatInZone(journey.departure_at, journey.timezone)}</td>
                  <td>{formatInZone(journey.scheduled_arrival_at, journey.timezone)}</td>
                  <td>
                    {journey.booked_passengers} / {journey.bus_capacity}
                  </td>
                  <td>
                    <span className={ui.badge}>{journey.status.replaceAll("_", " ")}</span>
                  </td>
                  <td>
                    <Link href={`/dashboard/journeys/${journey.id}`}>Open</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
