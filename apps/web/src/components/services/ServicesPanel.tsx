"use client";

import { Plus, Route as RouteIcon, Search, Trash2, Waypoints } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";

import { EmptyState, SkeletonRows } from "@/components/kit/bits";
import { ConfirmDialog, Modal } from "@/components/kit/Modal";
import { PlaceInput } from "@/components/kit/PlaceInput";
import { Pill } from "@/components/kit/StatusBadge";
import { useToast } from "@/components/kit/Toast";
import { authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { distanceKm, point, suggestOptions, type Place } from "@/lib/places";
import { addCorridorOption } from "@/lib/routeOptions";
import { km } from "@/lib/time";
import type { Service } from "@/lib/types";
import { useResource } from "@/lib/useResource";

import { PageHeader } from "../kit/PageHeader";
import ui from "../ui.module.css";
import styles from "./services.module.css";

export type { Service };

export function ServicesPanel() {
  const router = useRouter();
  const toast = useToast();
  const services = useResource<Service[]>("/api/v1/services");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [removing, setRemoving] = useState<Service | null>(null);
  const [busy, setBusy] = useState(false);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (services.data ?? []).filter(
      (s) => !q || `${s.origin_name} ${s.destination_name}`.toLowerCase().includes(q),
    );
  }, [services.data, query]);

  async function remove(service: Service) {
    setBusy(true);
    try {
      const result = await authedRequest<{ result: string }>(`/api/v1/services/${service.id}`, "DELETE");
      toast.success(
        result.result === "archived"
          ? `${service.origin_name} → ${service.destination_name} has journeys, so it was archived instead of deleted.`
          : `${service.origin_name} → ${service.destination_name} was removed.`,
      );
      setRemoving(null);
      services.reload();
    } catch (reason) {
      toast.failure(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={ui.stack}>
      <PageHeader
        title="Services"
        subtitle="Each service is an origin and destination you operate. Give it route options, then schedule journeys on it."
        actions={
          <button type="button" className={ui.button} onClick={() => setCreating(true)}>
            <Plus size={16} aria-hidden /> New service
          </button>
        }
      />

      <div className={styles.toolbar}>
        <label className={styles.search}>
          <Search size={16} aria-hidden />
          <input
            type="search"
            placeholder="Search by town, for example Pune"
            aria-label="Search services"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        {services.data && (
          <span className={ui.small}>
            {shown.length} of {services.data.length} services
          </span>
        )}
      </div>

      {services.error && (
        <p className={ui.error} role="alert" data-testid="panel-error">
          {services.error}
        </p>
      )}
      {services.loading && <SkeletonRows rows={3} height={132} />}
      {services.data && services.data.length === 0 && (
        <EmptyState
          icon={Waypoints}
          title="No services yet"
          action={
            <button type="button" className={ui.button} onClick={() => setCreating(true)}>
              <Plus size={16} aria-hidden /> Create your first service
            </button>
          }
        >
          Pick an origin and a destination from the Maharashtra map. Known corridors come with route options ready to use.
        </EmptyState>
      )}
      {services.data && services.data.length > 0 && shown.length === 0 && (
        <EmptyState icon={Search} title="No service matches">
          Try another town name.
        </EmptyState>
      )}

      <ul className={styles.grid} aria-label="Services">
        {shown.map((service) => (
          <li key={service.id} className={styles.card} data-testid="service-card">
            <Link href={`/dashboard/services/${service.id}`} className={styles.cardLink} aria-label={`${service.origin_name} to ${service.destination_name}`} />
            <div className={styles.legs}>
              <span className={styles.leg} data-end="from">
                {service.origin_name}
              </span>
              <span className={styles.leg} data-end="to">
                {service.destination_name}
              </span>
            </div>
            <div className={styles.facts}>
              <Pill tone={service.route_count ? "brand" : "warn"}>
                <RouteIcon size={13} aria-hidden />
                {service.route_count
                  ? `${service.route_count} route option${service.route_count === 1 ? "" : "s"}`
                  : "No route options yet"}
              </Pill>
              {service.shortest_m != null && (
                <span className={ui.small}>
                  {service.longest_m != null && service.longest_m !== service.shortest_m
                    ? `${km(service.shortest_m)} to ${km(service.longest_m)}`
                    : km(service.shortest_m)}
                </span>
              )}
            </div>
            <div className={styles.cardFoot}>
              <span className={ui.small}>
                {service.active_journeys ? `${service.active_journeys} open journey${service.active_journeys === 1 ? "" : "s"}` : "No open journeys"}
              </span>
              <button
                type="button"
                className={styles.trash}
                aria-label={`Remove ${service.origin_name} to ${service.destination_name}`}
                onClick={() => setRemoving(service)}
              >
                <Trash2 size={16} aria-hidden />
              </button>
            </div>
          </li>
        ))}
      </ul>

      <NewServiceDialog
        open={creating}
        existing={services.data ?? []}
        onClose={() => setCreating(false)}
        onCreated={(id) => {
          setCreating(false);
          services.reload();
          router.push(`/dashboard/services/${id}`);
        }}
      />
      <ConfirmDialog
        open={removing !== null}
        title="Remove this service?"
        message={
          removing && (
            <>
              <strong>
                {removing.origin_name} → {removing.destination_name}
              </strong>{" "}
              and its route options will be removed. A service that already has journeys is archived instead, so history is kept.
            </>
          )
        }
        confirmLabel="Remove service"
        busy={busy}
        onCancel={() => setRemoving(null)}
        onConfirm={() => removing && remove(removing)}
      />
    </div>
  );
}

function NewServiceDialog({
  open,
  existing,
  onClose,
  onCreated,
}: {
  open: boolean;
  existing: Service[];
  onClose: () => void;
  onCreated: (serviceId: string) => void;
}) {
  const toast = useToast();
  const [origin, setOrigin] = useState<Place | null>(null);
  const [destination, setDestination] = useState<Place | null>(null);
  const [addSuggested, setAddSuggested] = useState(true);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const suggestions = useMemo(
    () => (origin && destination ? suggestOptions(origin.name, destination.name) : []),
    [origin, destination],
  );
  const duplicate = useMemo(
    () =>
      origin && destination
        ? existing.find(
            (s) =>
              s.origin_name.toLowerCase() === origin.name.toLowerCase() &&
              s.destination_name.toLowerCase() === destination.name.toLowerCase(),
          )
        : undefined,
    [existing, origin, destination],
  );
  const straight = origin && destination ? Math.round(distanceKm(origin, destination)) : null;

  function close() {
    if (busy) return;
    setOrigin(null);
    setDestination(null);
    setError(null);
    setProgress(null);
    onClose();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!origin || !destination || duplicate) return;
    setBusy(true);
    setError(null);
    try {
      const service = await authedRequest<Service>("/api/v1/services", "POST", {
        origin_name: origin.name,
        destination_name: destination.name,
        origin_location: point(origin),
        destination_location: point(destination),
      });
      let failed = 0;
      if (addSuggested) {
        for (const [index, option] of suggestions.entries()) {
          setProgress(`Drawing route option ${index + 1} of ${suggestions.length}: ${option.name}`);
          try {
            const result = await addCorridorOption(service.id, option);
            if (result.generation_error) failed += 1;
          } catch {
            failed += 1;
          }
        }
      }
      toast.success(
        failed
          ? `Service created. ${failed} route option${failed === 1 ? "" : "s"} could not be drawn: add them from the service page.`
          : `${origin.name} → ${destination.name} is ready.`,
      );
      setOrigin(null);
      setDestination(null);
      setProgress(null);
      onCreated(service.id);
    } catch (reason) {
      setError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="New service"
      description="Choose where the bus starts and ends. Route options can be added now or later."
    >
      <form className={ui.stack} onSubmit={submit} aria-label="New service">
        <div className={styles.pair}>
          <PlaceInput label="Origin" value={origin} onChange={setOrigin} exclude={destination ? [destination.name] : []} />
          <PlaceInput label="Destination" value={destination} onChange={setDestination} exclude={origin ? [origin.name] : []} />
        </div>

        {duplicate && (
          <p className={ui.notice} role="status">
            You already run {duplicate.origin_name} → {duplicate.destination_name}.{" "}
            <Link href={`/dashboard/services/${duplicate.id}`} className={ui.link}>
              Open it
            </Link>
          </p>
        )}

        {origin && destination && !duplicate && (
          <div className={styles.preview}>
            <div>
              <strong>
                {origin.name} → {destination.name}
              </strong>
              <p className={ui.small}>About {straight} km as the crow flies.</p>
            </div>
            {suggestions.length > 0 ? (
              <label className={ui.checkboxRow}>
                <input type="checkbox" checked={addSuggested} onChange={(event) => setAddSuggested(event.target.checked)} />
                <span>
                  Add {suggestions.length} known route options
                  <small className={ui.hint} style={{ display: "block" }}>
                    {suggestions.map((s) => s.name).join(" · ")}
                  </small>
                </span>
              </label>
            ) : (
              <p className={ui.small}>No ready-made corridor for this pair. You will add route options by choosing towns on the road.</p>
            )}
          </div>
        )}

        {progress && (
          <p className={ui.notice} role="status">
            {progress}…
          </p>
        )}
        {error && (
          <p className={ui.error} role="alert">
            {error}
          </p>
        )}
        <div className={ui.rowCenter} style={{ justifyContent: "flex-end" }}>
          <button type="button" className={ui.buttonGhost} onClick={close} disabled={busy}>
            Cancel
          </button>
          <button className={ui.button} type="submit" disabled={busy || !origin || !destination || Boolean(duplicate)}>
            {busy ? "Creating…" : "Create service"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
