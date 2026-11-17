"use client";

import { Activity, ArrowRight, Bus as BusIcon, Check } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { ConfirmDialog, Modal } from "@/components/kit/Modal";
import { useToast } from "@/components/kit/Toast";
import { ApiError, authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import type { Bus, Journey } from "@/lib/types";
import { useResource } from "@/lib/useResource";

import ui from "../ui.module.css";
import styles from "./detail.module.css";

type Issue = { code: string; severity: "error" | "warning"; message: string };
type Transitions = { status: string; allowed: string[] };

export const STEPS = [
  { id: "draft", label: "Plan" },
  { id: "awaiting_confirmation", label: "Confirm" },
  { id: "ready", label: "Ready" },
  { id: "published", label: "Published" },
  { id: "boarding", label: "Boarding" },
  { id: "in_progress", label: "On the road" },
  { id: "completed", label: "Completed" },
] as const;

const PRIMARY: Record<string, { to: string; label: string; assign?: boolean; hint: string }> = {
  draft: {
    to: "awaiting_confirmation",
    label: "Submit plan",
    hint: "Choose a route, add bookings, confirm the stops, then submit the plan.",
  },
  awaiting_confirmation: {
    to: "ready",
    label: "Assign route",
    assign: true,
    hint: "The plan is submitted. Assigning the route calculates the road through every confirmed stop.",
  },
  ready: { to: "published", label: "Publish", hint: "The route is assigned. Publish to open the passenger link." },
  published: { to: "boarding", label: "Start boarding", hint: "Published. Start boarding when passengers arrive at the origin." },
  boarding: { to: "in_progress", label: "Mark departed", hint: "Boarding. Mark departed when the bus leaves the origin." },
  in_progress: { to: "completed", label: "Mark completed", hint: "The bus is on the road. Watch it on the live monitor." },
  disrupted: { to: "in_progress", label: "Resume journey", hint: "This journey is disrupted. Resume it once the road is clear." },
};

const SECONDARY: Record<string, string> = {
  draft: "Reopen for editing",
  disrupted: "Mark disrupted",
  cancelled: "Cancel journey",
};

/** The one next step, plus the less common status changes. */
export function JourneyActions({ journey, onChanged }: { journey: Journey; onChanged: () => void }) {
  const toast = useToast();
  const base = `/api/v1/journeys/${journey.id}`;
  const transitions = useResource<Transitions>(`${base}/transitions?v=${journey.status}`);
  const [busy, setBusy] = useState(false);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [cancelling, setCancelling] = useState(false);
  const [changingBus, setChangingBus] = useState(false);
  const buses = useResource<Bus[]>(changingBus ? "/api/v1/buses" : null);
  const [newBus, setNewBus] = useState("");

  async function saveBus(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await authedRequest(`${base}`, "PATCH", { bus_id: newBus });
      toast.success("Bus changed.");
      setChangingBus(false);
      onChanged();
    } catch (reason) {
      toast.failure(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  const primary = PRIMARY[journey.status];
  const allowed = transitions.data?.allowed ?? [];
  const secondary = allowed.filter((to) => to !== primary?.to && to !== "ready" && SECONDARY[to]);
  const monitorable = !["draft", "awaiting_confirmation"].includes(journey.status);

  async function move(to: string, assign = false) {
    setBusy(true);
    try {
      await authedRequest(assign ? `${base}/assign` : `${base}/transition`, "POST", assign ? undefined : { to });
      toast.success(
        assign
          ? "Route assigned. The journey is ready."
          : `Journey is now ${to.replaceAll("_", " ")}.`,
      );
      setCancelling(false);
      onChanged();
      transitions.reload();
    } catch (reason) {
      const details = reason instanceof ApiError ? (reason.details as { issues?: Issue[] } | undefined) : undefined;
      if (details?.issues?.length) setIssues(details.issues);
      else toast.failure(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.actions}>
      {monitorable && journey.status !== "completed" && journey.status !== "cancelled" && (
        <Link href={`/dashboard/journeys/${journey.id}/monitor`} className={ui.buttonGhost}>
          <Activity size={16} aria-hidden /> Live monitor
        </Link>
      )}
      {journey.status === "completed" && (
        <Link href={`/dashboard/journeys/${journey.id}/monitor`} className={ui.buttonGhost}>
          <Activity size={16} aria-hidden /> View monitor
        </Link>
      )}
      {journey.status === "draft" && (
        <button type="button" className={ui.buttonGhost} onClick={() => setChangingBus(true)} disabled={busy}>
          <BusIcon size={16} aria-hidden /> Change bus
        </button>
      )}
      {secondary.map((to) => (
        <button
          key={to}
          type="button"
          className={to === "cancelled" ? ui.buttonDanger : ui.buttonGhost}
          disabled={busy}
          onClick={() => (to === "cancelled" ? setCancelling(true) : move(to))}
        >
          {SECONDARY[to]}
        </button>
      ))}
      {primary && allowed.includes(primary.to) && (
        <button
          type="button"
          className={ui.button}
          disabled={busy}
          onClick={() => move(primary.to, primary.assign)}
          data-testid="primary-action"
        >
          {busy ? "Working…" : primary.label}
          {!busy && <ArrowRight size={16} aria-hidden />}
        </button>
      )}

      <ConfirmDialog
        open={cancelling}
        title="Cancel this journey?"
        message="Passengers with an active link will see that the journey was cancelled. This cannot be undone."
        confirmLabel="Cancel journey"
        busy={busy}
        onCancel={() => setCancelling(false)}
        onConfirm={() => move("cancelled")}
      />
      <Modal
        open={changingBus}
        onClose={() => setChangingBus(false)}
        title="Change bus"
        description="Only a draft journey can change its bus. The seat count of the new bus applies to bookings."
      >
        <form className={ui.stack} onSubmit={saveBus} aria-label="Change bus">
          <label className={ui.field}>
            Bus
            <select required value={newBus} onChange={(event) => setNewBus(event.target.value)}>
              <option value="" disabled>
                Choose a bus…
              </option>
              {(buses.data ?? [])
                .filter((bus) => bus.status === "active" && bus.id !== journey.bus_id)
                .map((bus) => (
                  <option key={bus.id} value={bus.id}>
                    {bus.registration} · {bus.capacity} seats
                  </option>
                ))}
            </select>
          </label>
          <div className={ui.rowCenter} style={{ justifyContent: "flex-end" }}>
            <button type="button" className={ui.buttonGhost} onClick={() => setChangingBus(false)}>
              Cancel
            </button>
            <button type="submit" className={ui.button} disabled={busy || !newBus}>
              {busy ? "Saving…" : "Change bus"}
            </button>
          </div>
        </form>
      </Modal>
      <Modal
        open={issues.length > 0}
        onClose={() => setIssues([])}
        title="The plan needs attention"
        description="Fix these, then try again."
      >
        <ul className={styles.issueList}>
          {issues.map((issue) => (
            <li key={issue.code + issue.message} data-severity={issue.severity}>
              <strong>{issue.severity === "error" ? "Problem" : "Note"}</strong>
              {issue.message}
            </li>
          ))}
        </ul>
        <div className={ui.rowCenter} style={{ justifyContent: "flex-end", marginTop: 16 }}>
          <button type="button" className={ui.button} onClick={() => setIssues([])}>
            <Check size={16} aria-hidden /> Got it
          </button>
        </div>
      </Modal>
    </div>
  );
}

export function nextHint(status: string): string | null {
  return PRIMARY[status]?.hint ?? null;
}
