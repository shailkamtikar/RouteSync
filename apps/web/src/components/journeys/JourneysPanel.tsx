"use client";

import { CalendarClock, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";

import { Chips, EmptyState, RouteLabel, SkeletonRows } from "@/components/kit/bits";
import { Modal } from "@/components/kit/Modal";
import { PageHeader } from "@/components/kit/PageHeader";
import { StatusBadge } from "@/components/kit/StatusBadge";
import { useToast } from "@/components/kit/Toast";
import { authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatDay, formatDuration, formatInZone, km, zonedInputToIso } from "@/lib/time";
import { TIME_ZONE, type Bus, type Journey, type RouteTemplate, type Service } from "@/lib/types";
import { useResource } from "@/lib/useResource";

import ui from "../ui.module.css";
import styles from "./journeys.module.css";

export type { Journey };

type Group = "all" | "live" | "upcoming" | "planning" | "past";
const GROUPS: Record<Exclude<Group, "all">, string[]> = {
  live: ["boarding", "in_progress", "disrupted"],
  upcoming: ["published", "ready"],
  planning: ["draft", "awaiting_confirmation"],
  past: ["completed", "cancelled"],
};
const GROUP_TITLE: Record<Exclude<Group, "all">, string> = {
  live: "On the road",
  upcoming: "Upcoming",
  planning: "Being planned",
  past: "Past",
};

function groupOf(status: string): Exclude<Group, "all"> {
  return (Object.keys(GROUPS) as (keyof typeof GROUPS)[]).find((g) => GROUPS[g].includes(status)) ?? "past";
}

export function JourneysPanel() {
  const router = useRouter();
  const params = useSearchParams();
  const journeys = useResource<Journey[]>("/api/v1/journeys");
  const [group, setGroup] = useState<Group>("all");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(params.get("new") === "1");

  const all = useMemo(() => journeys.data ?? [], [journeys.data]);
  const counts = useMemo(() => {
    const result: Record<Group, number> = { all: all.length, live: 0, upcoming: 0, planning: 0, past: 0 };
    for (const j of all) result[groupOf(j.status)] += 1;
    return result;
  }, [all]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return all.filter(
      (j) =>
        (group === "all" || groupOf(j.status) === group) &&
        (!q || `${j.origin_name} ${j.destination_name} ${j.bus_registration}`.toLowerCase().includes(q)),
    );
  }, [all, group, query]);

  const sections = useMemo(() => {
    const order: (keyof typeof GROUPS)[] = ["live", "upcoming", "planning", "past"];
    return order
      .map((key) => ({
        key,
        rows: filtered
          .filter((j) => groupOf(j.status) === key)
          .sort((a, b) =>
            key === "past" ? b.departure_at.localeCompare(a.departure_at) : a.departure_at.localeCompare(b.departure_at),
          ),
      }))
      .filter((section) => section.rows.length > 0);
  }, [filtered]);

  return (
    <div className={ui.stack}>
      <PageHeader
        title="Journeys"
        subtitle="Every departure, from the first draft to the last passenger dropped."
        actions={
          <button type="button" className={ui.button} onClick={() => setCreating(true)}>
            <Plus size={16} aria-hidden /> New journey
          </button>
        }
      />

      <div className={styles.toolbar}>
        <Chips
          label="Filter journeys"
          value={group}
          onChange={setGroup}
          options={[
            { id: "all", label: "All", count: counts.all },
            { id: "live", label: "On the road", count: counts.live },
            { id: "upcoming", label: "Upcoming", count: counts.upcoming },
            { id: "planning", label: "Planning", count: counts.planning },
            { id: "past", label: "Past", count: counts.past },
          ]}
        />
        <label className={styles.search}>
          <Search size={16} aria-hidden />
          <input
            type="search"
            placeholder="Town or bus number"
            aria-label="Search journeys"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>

      {journeys.error && (
        <p className={ui.error} role="alert" data-testid="panel-error">
          {journeys.error}
        </p>
      )}
      {journeys.loading && <SkeletonRows rows={5} height={68} />}
      {journeys.data && all.length === 0 && (
        <EmptyState
          icon={CalendarClock}
          title="No journeys yet"
          action={
            <button type="button" className={ui.button} onClick={() => setCreating(true)}>
              <Plus size={16} aria-hidden /> Schedule a journey
            </button>
          }
        >
          A journey is one departure of a bus on a service. Create one to start taking bookings.
        </EmptyState>
      )}
      {journeys.data && all.length > 0 && filtered.length === 0 && (
        <EmptyState icon={Search} title="Nothing matches">
          Clear the search or choose another filter.
        </EmptyState>
      )}

      {sections.map(({ key, rows }) => (
        <section key={key} aria-label={GROUP_TITLE[key]} className={styles.section}>
          <h2 className={styles.sectionHead}>
            {GROUP_TITLE[key]} <span>{rows.length}</span>
          </h2>
          <ul className={styles.list}>
            {rows.map((journey) => {
              const fill = Math.min(100, Math.round((journey.booked_passengers / Math.max(1, journey.bus_capacity)) * 100));
              return (
                <li key={journey.id} data-testid="journey-row">
                  <Link href={`/dashboard/journeys/${journey.id}`} className={styles.item}>
                    <div className={styles.when}>
                      <strong>{formatDay(journey.departure_at, journey.timezone)}</strong>
                      <small>arrives {formatInZone(journey.scheduled_arrival_at, journey.timezone).split(", ").pop()}</small>
                    </div>
                    <div className={styles.route}>
                      <RouteLabel from={journey.origin_name} to={journey.destination_name} />
                      <small>{journey.bus_registration}</small>
                    </div>
                    <div className={styles.pax} aria-label={`${journey.booked_passengers} of ${journey.bus_capacity} seats booked`}>
                      <div className={styles.bar}>
                        <span style={{ width: `${fill}%` }} data-full={fill >= 90} />
                      </div>
                      <small>
                        {journey.booked_passengers} / {journey.bus_capacity} booked
                      </small>
                    </div>
                    <StatusBadge status={journey.status} />
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      ))}

      <NewJourneyDialog
        open={creating}
        onClose={() => {
          setCreating(false);
          if (params.get("new")) router.replace("/dashboard/journeys");
        }}
        onCreated={(id) => {
          setCreating(false);
          router.push(`/dashboard/journeys/${id}`);
        }}
      />
    </div>
  );
}

function defaultDeparture(): string {
  // Next full hour from now, in the journey's time zone, in <input type="datetime-local"> form.
  const next = new Date(Math.ceil((Date.now() + 30 * 60_000) / 3_600_000) * 3_600_000);
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(next);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "00";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour") === "24" ? "00" : get("hour")}:${get("minute")}`;
}

function addMinutesLocal(local: string, minutes: number): string {
  const instant = new Date(zonedInputToIso(local, TIME_ZONE)).getTime() + minutes * 60_000;
  const rounded = new Date(Math.round(instant / 300_000) * 300_000);
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(rounded);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "00";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour") === "24" ? "00" : get("hour")}:${get("minute")}`;
}

function NewJourneyDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (journeyId: string) => void;
}) {
  const toast = useToast();
  const services = useResource<Service[]>(open ? "/api/v1/services" : null);
  const buses = useResource<Bus[]>(open ? "/api/v1/buses" : null);
  const [serviceId, setServiceId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [busId, setBusId] = useState("");
  const [departure, setDeparture] = useState(defaultDeparture);
  const [arrival, setArrival] = useState("");
  const [arrivalTouched, setArrivalTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const templates = useResource<RouteTemplate[]>(serviceId ? `/api/v1/services/${serviceId}/route-templates` : null);

  const ready = useMemo(() => (templates.data ?? []).filter((t) => t.status === "ready"), [templates.data]);
  const chosen = ready.find((t) => t.id === templateId) ?? ready[0] ?? null;
  const estimatedMinutes = chosen?.duration_s ? (chosen.duration_s / 60) * 1.12 : null;
  const effectiveArrival = arrivalTouched
    ? arrival
    : estimatedMinutes && departure
      ? addMinutesLocal(departure, estimatedMinutes)
      : arrival;
  const activeServices = services.data ?? [];
  const activeBuses = (buses.data ?? []).filter((b) => b.status === "active");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const journey = await authedRequest<Journey>("/api/v1/journeys", "POST", {
        bus_id: busId,
        service_id: serviceId,
        departure_at: zonedInputToIso(departure, TIME_ZONE),
        scheduled_arrival_at: zonedInputToIso(effectiveArrival, TIME_ZONE),
        timezone: TIME_ZONE,
      });
      if (chosen) {
        await authedRequest(`/api/v1/journeys/${journey.id}/route-template`, "PUT", { route_template_id: chosen.id });
      }
      toast.success("Journey created. Add bookings and confirm the stops next.");
      onCreated(journey.id);
    } catch (reason) {
      setError(reason instanceof Error && reason.name === "Error" ? reason.message : describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  const noData = !services.loading && !buses.loading && (activeServices.length === 0 || activeBuses.length === 0);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New journey"
      description="One departure of a bus on a service. You can change the route option until the plan is confirmed."
    >
      <form className={ui.stack} onSubmit={submit} aria-label="New journey">
        <label className={ui.field}>
          Service
          <select
            required
            value={serviceId}
            onChange={(event) => {
              setServiceId(event.target.value);
              setTemplateId("");
            }}
          >
            <option value="" disabled>
              Choose a service…
            </option>
            {activeServices.map((service) => (
              <option key={service.id} value={service.id}>
                {service.origin_name} → {service.destination_name}
              </option>
            ))}
          </select>
        </label>
        {serviceId && (
          <label className={ui.field}>
            Route option
            <select value={chosen?.id ?? ""} onChange={(event) => setTemplateId(event.target.value)} disabled={ready.length === 0}>
              {ready.length === 0 && <option value="">{templates.loading ? "Loading…" : "No ready route option"}</option>}
              {ready.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name} · {km(template.distance_m)}
                  {template.duration_s ? ` · ${formatDuration(template.duration_s)}` : ""}
                </option>
              ))}
            </select>
            {!templates.loading && ready.length === 0 && (
              <span className={ui.hint}>Add a route option on the service page first, or choose one later.</span>
            )}
          </label>
        )}
        <label className={ui.field}>
          Bus
          <select required value={busId} onChange={(event) => setBusId(event.target.value)}>
            <option value="" disabled>
              Choose a bus…
            </option>
            {activeBuses.map((bus) => (
              <option key={bus.id} value={bus.id}>
                {bus.registration} · {bus.capacity} seats
              </option>
            ))}
          </select>
        </label>
        <div className={ui.row} style={{ alignItems: "stretch" }}>
          <label className={ui.field} style={{ flex: 1 }}>
            Departure (IST)
            <input type="datetime-local" required value={departure} onChange={(event) => setDeparture(event.target.value)} />
          </label>
          <label className={ui.field} style={{ flex: 1 }}>
            Scheduled arrival (IST)
            <input
              type="datetime-local"
              required
              value={effectiveArrival}
              onChange={(event) => {
                setArrivalTouched(true);
                setArrival(event.target.value);
              }}
            />
            {!arrivalTouched && estimatedMinutes && (
              <span className={ui.hint}>Drive time plus a 12% margin. Edit to override.</span>
            )}
          </label>
        </div>
        {noData && (
          <p className={ui.notice}>Add at least one service and one bus before scheduling a journey.</p>
        )}
        {error && (
          <p className={ui.error} role="alert">
            {error}
          </p>
        )}
        <div className={ui.rowCenter} style={{ justifyContent: "flex-end" }}>
          <button type="button" className={ui.buttonGhost} onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className={ui.button} type="submit" disabled={busy || !serviceId || !busId || !effectiveArrival}>
            {busy ? "Creating…" : "Create journey"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
