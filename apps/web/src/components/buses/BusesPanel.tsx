"use client";

import { Armchair, Bus as BusIcon, Pencil, Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type FormEvent } from "react";

import { EmptyState, SkeletonRows } from "@/components/kit/bits";
import { ConfirmDialog, Modal } from "@/components/kit/Modal";
import { PageHeader } from "@/components/kit/PageHeader";
import { Pill } from "@/components/kit/StatusBadge";
import { useToast } from "@/components/kit/Toast";
import { authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatDay } from "@/lib/time";
import { LIVE_STATUSES, type Bus, type Journey } from "@/lib/types";
import { useResource } from "@/lib/useResource";

import ui from "../ui.module.css";
import styles from "./buses.module.css";

export type { Bus };

export function BusesPanel() {
  const toast = useToast();
  const buses = useResource<Bus[]>("/api/v1/buses");
  const journeys = useResource<Journey[]>("/api/v1/journeys");
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<Bus | "new" | null>(null);
  const [removing, setRemoving] = useState<Bus | null>(null);
  const [busy, setBusy] = useState(false);
  const [now] = useState(() => Date.now());

  const usage = useMemo(() => {
    const map = new Map<string, { live?: Journey; next?: Journey; count: number }>();
    for (const journey of journeys.data ?? []) {
      const entry = map.get(journey.bus_id) ?? { count: 0 };
      entry.count += 1;
      if (LIVE_STATUSES.includes(journey.status)) entry.live = journey;
      else if (
        !["completed", "cancelled"].includes(journey.status) &&
        new Date(journey.departure_at).getTime() > now - 3600_000 &&
        (!entry.next || journey.departure_at < entry.next.departure_at)
      )
        entry.next = journey;
      map.set(journey.bus_id, entry);
    }
    return map;
  }, [journeys.data, now]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (buses.data ?? []).filter((bus) => !q || bus.registration.toLowerCase().includes(q));
  }, [buses.data, query]);
  const seats = useMemo(
    () => (buses.data ?? []).filter((b) => b.status === "active").reduce((sum, b) => sum + b.capacity, 0),
    [buses.data],
  );

  async function remove(bus: Bus) {
    setBusy(true);
    try {
      const result = await authedRequest<{ result: string }>(`/api/v1/buses/${bus.id}`, "DELETE");
      toast.success(
        result.result === "archived"
          ? `${bus.registration} has journeys on record, so it was archived instead of deleted.`
          : `${bus.registration} was removed.`,
      );
      setRemoving(null);
      buses.reload();
    } catch (reason) {
      toast.failure(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={ui.stack}>
      <PageHeader
        title="Buses"
        subtitle={
          buses.data
            ? `${buses.data.filter((b) => b.status === "active").length} buses and ${seats} seats in your fleet.`
            : "Your fleet."
        }
        actions={
          <button type="button" className={ui.button} onClick={() => setEditing("new")}>
            <Plus size={16} aria-hidden /> Add bus
          </button>
        }
      />

      <label className={styles.search}>
        <Search size={16} aria-hidden />
        <input
          type="search"
          placeholder="Search by registration"
          aria-label="Search buses"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>

      {buses.error && (
        <p className={ui.error} role="alert" data-testid="panel-error">
          {buses.error}
        </p>
      )}
      {buses.loading && <SkeletonRows rows={4} height={72} />}
      {buses.data?.length === 0 && (
        <EmptyState
          icon={BusIcon}
          title="No buses yet"
          action={
            <button type="button" className={ui.button} onClick={() => setEditing("new")}>
              <Plus size={16} aria-hidden /> Add your first bus
            </button>
          }
        >
          Add the buses you run. Capacity limits how many passengers a journey can book.
        </EmptyState>
      )}

      <ul className={styles.grid} aria-label="Buses">
        {shown.map((bus) => {
          const info = usage.get(bus.id);
          return (
            <li key={bus.id} className={styles.card} data-testid="bus-card">
              <div className={styles.top}>
                <span className={styles.plate}>{bus.registration}</span>
                {bus.status === "archived" ? (
                  <Pill>Archived</Pill>
                ) : info?.live ? (
                  <Pill tone="ok">On the road</Pill>
                ) : info?.next ? (
                  <Pill tone="brand">Scheduled</Pill>
                ) : (
                  <Pill>Available</Pill>
                )}
              </div>
              <div className={styles.facts}>
                <span>
                  <Armchair size={15} aria-hidden /> {bus.capacity} seats
                </span>
                <span>
                  {info?.count ?? 0} journey{info?.count === 1 ? "" : "s"}
                </span>
              </div>
              <p className={styles.next}>
                {info?.live ? (
                  <Link href={`/dashboard/journeys/${info.live.id}/monitor`} className={ui.link}>
                    {info.live.origin_name} → {info.live.destination_name} · live
                  </Link>
                ) : info?.next ? (
                  <Link href={`/dashboard/journeys/${info.next.id}`} className={ui.link}>
                    {formatDay(info.next.departure_at, info.next.timezone)} · {info.next.origin_name} → {info.next.destination_name}
                  </Link>
                ) : (
                  <span className={ui.small}>No upcoming journey.</span>
                )}
              </p>
              <div className={styles.actions}>
                <button
                  type="button"
                  className={`${ui.buttonGhost} ${ui.sm}`}
                  onClick={() => setEditing(bus)}
                  aria-label={`Edit ${bus.registration}`}
                >
                  <Pencil size={14} aria-hidden /> Edit
                </button>
                <button
                  type="button"
                  className={`${ui.buttonDanger} ${ui.sm}`}
                  onClick={() => setRemoving(bus)}
                  aria-label={`Remove ${bus.registration}`}
                >
                  <Trash2 size={14} aria-hidden /> Remove
                </button>
              </div>
            </li>
          );
        })}
      </ul>

      <BusDialog
        bus={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          buses.reload();
        }}
      />
      <ConfirmDialog
        open={removing !== null}
        title="Remove this bus?"
        message={
          removing && (
            <>
              <strong>{removing.registration}</strong> will be removed from your fleet. A bus with journeys on record is archived instead.
            </>
          )
        }
        confirmLabel="Remove bus"
        busy={busy}
        onCancel={() => setRemoving(null)}
        onConfirm={() => removing && remove(removing)}
      />
    </div>
  );
}

function BusDialog({
  bus,
  onClose,
  onSaved,
}: {
  bus: Bus | "new" | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const existing = bus && bus !== "new" ? bus : null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      if (existing) {
        await authedRequest(`/api/v1/buses/${existing.id}`, "PATCH", {
          capacity: Number(data.get("capacity")),
          expected_updated_at: existing.updated_at,
        });
        toast.success(`${existing.registration} updated.`);
      } else {
        const registration = String(data.get("registration") ?? "");
        await authedRequest("/api/v1/buses", "POST", { registration, capacity: Number(data.get("capacity")) });
        toast.success(`${registration.toUpperCase()} added to your fleet.`);
      }
      onSaved();
    } catch (reason) {
      setError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={bus !== null}
      onClose={onClose}
      title={existing ? `Edit ${existing.registration}` : "Add a bus"}
      description={existing ? "Capacity changes apply to journeys that are not yet full." : "Use the registration printed on the vehicle."}
    >
      {bus !== null && (
        <form className={ui.stack} onSubmit={submit} aria-label={existing ? "Edit bus" : "Add bus"}>
          {!existing && (
            <label className={ui.field}>
              Registration
              <input name="registration" required minLength={4} maxLength={20} placeholder="MH12 AB 1234" autoFocus />
              <span className={ui.hint}>Letters, digits, spaces or hyphens.</span>
            </label>
          )}
          <label className={ui.field}>
            Seats
            <input name="capacity" type="number" required min={1} max={100} defaultValue={existing?.capacity ?? 40} />
          </label>
          {error && (
            <p className={ui.error} role="alert">
              {error}
            </p>
          )}
          <div className={ui.rowCenter} style={{ justifyContent: "flex-end" }}>
            <button type="button" className={ui.buttonGhost} onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className={ui.button} disabled={busy}>
              {busy ? "Saving…" : existing ? "Save changes" : "Add bus"}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
