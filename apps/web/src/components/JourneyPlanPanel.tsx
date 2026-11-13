"use client";

import { useMemo, useState } from "react";

import { ApiError, authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatDuration, formatInZone } from "@/lib/time";
import { useResource } from "@/lib/useResource";

import type { Journey } from "./JourneysPanel";
import ui from "./ui.module.css";

type PlanStop = {
  route_template_stop_id: string;
  name: string;
  role: string;
  kind: string;
  chainage_m: number | null;
  active: boolean;
  pickup_count: number;
  drop_count: number;
  dwell_minutes: number;
  booked_pickups: number;
  booked_drops: number;
};
type StopPlan = {
  route_template_id: string | null;
  editable: boolean;
  plan_needs_review: boolean;
  stops: PlanStop[];
  unresolved_bookings: { reference: string; pickup_stop_name: string | null; drop_stop_name: string | null }[];
};
type Issue = { code: string; severity: "error" | "warning"; message: string };
type Validation = { valid: boolean; issues: Issue[] };
type Transitions = { status: string; allowed: string[] };
type RouteVersion = {
  id: string;
  version: number;
  distance_m: number | null;
  duration_s: number | null;
  reason: string;
  source: string;
  is_current: boolean;
  created_at: string;
};
type Draft = Record<string, { active: boolean; pickup: number; drop: number; dwell: number }>;

const ACTION_LABELS: Record<string, string> = {
  awaiting_confirmation: "Submit plan for confirmation",
  draft: "Reopen for editing",
  published: "Publish",
  boarding: "Start boarding",
  in_progress: "Mark departed",
  completed: "Mark completed",
  disrupted: "Mark disrupted",
  cancelled: "Cancel journey",
};

function toDraft(stops: PlanStop[]): Draft {
  return Object.fromEntries(
    stops.map((stop) => [
      stop.route_template_stop_id,
      {
        active: stop.active,
        pickup: stop.active ? stop.pickup_count : stop.booked_pickups,
        drop: stop.active ? stop.drop_count : stop.booked_drops,
        dwell: stop.dwell_minutes,
      },
    ]),
  );
}

/** Stop confirmation, plan check, status actions and route history for one journey. */
export function JourneyPlanPanel({ journey, onChanged }: { journey: Journey; onChanged: () => void }) {
  const base = `/api/v1/journeys/${journey.id}`;
  // Reload whenever the journey itself changes (bookings, route option, status).
  const stamp = `${journey.status}|${journey.route_template_id}|${journey.booked_passengers}`;
  const plan = useResource<StopPlan>(`${base}/stop-plan?v=${encodeURIComponent(stamp)}`);
  const transitions = useResource<Transitions>(`${base}/transitions?v=${encodeURIComponent(stamp)}`);
  const versions = useResource<RouteVersion[]>(`${base}/route-versions?v=${encodeURIComponent(stamp)}`);
  // Local edits on top of the server state; cleared whenever the plan is saved or reloaded.
  const [edits, setEdits] = useState<Draft>({});
  const [validation, setValidation] = useState<Validation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [blocking, setBlocking] = useState<Issue[]>([]);
  const [busy, setBusy] = useState(false);

  const draft = useMemo(
    () => ({ ...toDraft(plan.data?.stops ?? []), ...edits }),
    [plan.data, edits],
  );

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setBlocking([]);
    try {
      await action();
    } catch (reason) {
      setError(describeError(reason));
      const details = reason instanceof ApiError ? (reason.details as { issues?: Issue[] }) : null;
      if (details?.issues) setBlocking(details.issues);
    } finally {
      setBusy(false);
    }
  }

  function refresh() {
    setEdits({});
    plan.reload();
    transitions.reload();
    versions.reload();
    onChanged();
  }

  const confirmStops = () =>
    run(async () => {
      await authedRequest(`${base}/active-stops`, "PUT", {
        stops: Object.entries(draft)
          .filter(([, value]) => value.active)
          .map(([id, value]) => ({
            route_template_stop_id: id,
            pickup_count: value.pickup,
            drop_count: value.drop,
            dwell_minutes: value.dwell,
          })),
      });
      setValidation(null);
      refresh();
    });

  const checkPlan = () =>
    run(async () => setValidation(await authedRequest<Validation>(`${base}/validate`, "POST")));

  const act = (path: string, body?: unknown) =>
    run(async () => {
      await authedRequest(`${base}/${path}`, "POST", body);
      setValidation(null);
      refresh();
    });

  function update(id: string, patch: Partial<Draft[string]>) {
    setEdits((current) => ({ ...current, [id]: { ...draft[id], ...patch } }));
  }

  const editable = plan.data?.editable ?? false;
  const loadError = plan.error ?? transitions.error ?? versions.error;

  return (
    <section className={ui.stack} aria-label="Stop plan">
      <h2>Stops and plan</h2>
      {!journey.route_template_id && (
        <p className={ui.muted}>Choose a route option above to see its stops.</p>
      )}

      {plan.data && plan.data.unresolved_bookings.length > 0 && (
        <ul className={ui.error} data-testid="unresolved-bookings">
          {plan.data.unresolved_bookings.map((booking) => (
            <li key={booking.reference}>
              Booking {booking.reference}:{" "}
              {[booking.pickup_stop_name, booking.drop_stop_name].filter(Boolean).join(" and ")} is
              not a stop on this route option.
            </li>
          ))}
        </ul>
      )}

      {plan.data && plan.data.stops.length > 0 && (
        <div className={ui.tableWrap}>
          <table className={ui.table} aria-label="Stop plan">
            <thead>
              <tr>
                <th>Active</th>
                <th>Stop</th>
                <th>From bookings</th>
                <th>Boarding</th>
                <th>Alighting</th>
                <th>Wait (min)</th>
              </tr>
            </thead>
            <tbody>
              {plan.data.stops.map((stop) => {
                const id = stop.route_template_stop_id;
                const value = draft[id];
                const passThrough = stop.kind === "pass_through";
                if (!value) return null;
                return (
                  <tr key={id} className={passThrough ? ui.muted : undefined}>
                    <td>
                      {passThrough ? (
                        "—"
                      ) : (
                        <input
                          type="checkbox"
                          checked={value.active}
                          disabled={!editable}
                          aria-label={`${stop.name} active`}
                          onChange={(event) => update(id, { active: event.target.checked })}
                        />
                      )}
                    </td>
                    <td>
                      {stop.name}
                      {stop.role !== "intermediate" && <span className={ui.muted}> ({stop.role})</span>}
                    </td>
                    <td>
                      {passThrough
                        ? "No passenger stop"
                        : `${stop.booked_pickups} board, ${stop.booked_drops} alight`}
                    </td>
                    {(["pickup", "drop", "dwell"] as const).map((field) => (
                      <td key={field}>
                        {!passThrough && (
                          <label className={ui.field}>
                            <input
                              type="number"
                              min={0}
                              max={field === "dwell" ? 120 : 100}
                              value={value[field]}
                              disabled={!editable || !value.active}
                              aria-label={`${stop.name} ${field}`}
                              style={{ width: 72 }}
                              onChange={(event) => update(id, { [field]: Number(event.target.value) })}
                            />
                          </label>
                        )}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className={ui.row}>
        {editable && journey.route_template_id && (
          <button className={ui.button} type="button" disabled={busy} onClick={confirmStops}>
            Confirm active stops
          </button>
        )}
        {journey.route_template_id && (
          <button className={ui.buttonGhost} type="button" disabled={busy} onClick={checkPlan}>
            Check plan
          </button>
        )}
        {journey.status === "awaiting_confirmation" && (
          <button className={ui.button} type="button" disabled={busy} onClick={() => act("assign")}>
            Assign route
          </button>
        )}
        {transitions.data?.allowed
          .filter((to) => to !== "ready")
          .map((to) => (
            <button
              key={to}
              className={to === "cancelled" ? ui.buttonDanger : ui.buttonGhost}
              type="button"
              disabled={busy}
              onClick={() => act("transition", { to })}
            >
              {ACTION_LABELS[to] ?? to}
            </button>
          ))}
      </div>

      {(error ?? loadError) && (
        <p className={ui.error} data-testid="plan-error">
          {error ?? loadError}
        </p>
      )}
      {blocking.length > 0 && (
        <ul className={ui.error} data-testid="plan-blocking">
          {blocking.map((issue) => (
            <li key={issue.code + issue.message}>{issue.message}</li>
          ))}
        </ul>
      )}
      {validation && (
        <div data-testid="plan-validation" role="status">
          {validation.issues.length === 0 ? (
            <p>The plan is consistent.</p>
          ) : (
            <ul>
              {validation.issues.map((issue) => (
                <li key={issue.code + issue.message} className={issue.severity === "error" ? ui.error : ui.muted}>
                  {issue.severity === "error" ? "Problem" : "Note"}: {issue.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {versions.data && versions.data.length > 0 && (
        <div className={ui.tableWrap}>
          <table className={ui.table} aria-label="Route versions">
            <thead>
              <tr>
                <th>Version</th>
                <th>Reason</th>
                <th>Distance</th>
                <th>Drive time</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {versions.data.map((version) => (
                <tr key={version.id}>
                  <td>
                    v{version.version} {version.is_current && <span className={ui.badge}>current</span>}
                  </td>
                  <td>{version.reason}</td>
                  <td>{version.distance_m === null ? "—" : `${(version.distance_m / 1000).toFixed(0)} km`}</td>
                  <td>{version.duration_s === null ? "—" : formatDuration(version.duration_s)}</td>
                  <td>{formatInZone(version.created_at, journey.timezone)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
