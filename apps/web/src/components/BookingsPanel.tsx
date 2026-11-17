"use client";

import { Download, Plus, Ticket, Trash2, Upload } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import { ApiError, authedRequest, authedUpload } from "@/lib/api";
import { describeError } from "@/lib/errors";
import type { RouteStop } from "@/lib/types";
import { useResource } from "@/lib/useResource";

import { EmptyState } from "./kit/bits";
import { Pill } from "./kit/StatusBadge";
import { useToast } from "./kit/Toast";
import ui from "./ui.module.css";

type Passenger = { id: string; name: string; seat_number: string | null };
export type Booking = {
  id: string;
  reference: string;
  contact_name: string | null;
  passenger_count: number;
  pickup_stop_name: string;
  drop_stop_name: string;
  pickup_stop_id: string | null;
  drop_stop_id: string | null;
  status: string;
  passengers: Passenger[];
};
type WriteResult = { capacity_warning: boolean };
type ImportProblem = { line: number; error: string };

const CSV_HEADER = "reference,contact_name,passenger_count,pickup_stop,drop_stop";

export function BookingsPanel({
  journeyId,
  routeTemplateId,
  capacity,
  editable,
  onChanged,
}: {
  journeyId: string;
  routeTemplateId: string | null;
  capacity: number;
  editable: boolean;
  onChanged: () => void;
}) {
  const toast = useToast();
  const base = `/api/v1/journeys/${journeyId}/bookings`;
  const { data: bookings, error: loadError, reload, loading } = useResource<Booking[]>(base);
  const stopList = useResource<RouteStop[]>(
    routeTemplateId ? `/api/v1/route-templates/${routeTemplateId}/stops` : null,
  );
  const [problems, setProblems] = useState<ImportProblem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pickup, setPickup] = useState("");
  const [showCancelled, setShowCancelled] = useState(false);

  const stops = useMemo(
    () => (stopList.data ?? []).filter((stop) => stop.kind === "passenger_stop"),
    [stopList.data],
  );
  const pickupIndex = stops.findIndex((stop) => stop.name === pickup);
  const dropOptions = pickupIndex >= 0 ? stops.slice(pickupIndex + 1) : stops;
  const confirmed = (bookings ?? []).filter((b) => b.status === "confirmed");
  const booked = confirmed.reduce((sum, b) => sum + b.passenger_count, 0);
  const visible = (bookings ?? []).filter((b) => showCancelled || b.status === "confirmed");

  async function run(action: () => Promise<WriteResult | unknown>, done: string) {
    setBusy(true);
    setError(null);
    setProblems([]);
    try {
      const result = (await action()) as Partial<WriteResult> | undefined;
      if (result?.capacity_warning) toast.failure(`${done} Booked passengers now exceed the bus capacity.`);
      else toast.success(done);
      reload();
      onChanged();
      return true;
    } catch (reason) {
      setError(describeError(reason));
      if (reason instanceof ApiError && Array.isArray(reason.details)) {
        setProblems(reason.details as ImportProblem[]);
      }
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const names = String(data.get("passenger_names") ?? "")
      .split(",")
      .map((name) => name.trim())
      .filter(Boolean);
    const ok = await run(
      () =>
        authedRequest(base, "POST", {
          contact_name: String(data.get("contact_name") ?? "").trim() || null,
          passenger_count: Number(data.get("passenger_count")),
          pickup_stop_name: String(data.get("pickup_stop_name") ?? ""),
          drop_stop_name: String(data.get("drop_stop_name") ?? ""),
          passengers: names.map((name) => ({ name })),
        }),
      "Booking added.",
    );
    if (ok) {
      form.reset();
      setPickup("");
    }
  }

  async function onImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = new FormData(form).get("file");
    if (!(file instanceof File) || file.size === 0) {
      setError("Choose a CSV file first.");
      return;
    }
    const ok = await run(async () => authedUpload(`${base}/import`, await file.text(), "text/csv"), "Bookings imported.");
    if (ok) form.reset();
  }

  function downloadSample() {
    const first = stops[0]?.name ?? "Pune";
    const last = stops[stops.length - 1]?.name ?? "Nanded";
    const text = `${CSV_HEADER}\nBK-1001,Asha Patil,2,${first},${last}\n`;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
    link.download = "bookings-sample.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  }

  const fill = Math.min(100, Math.round((booked / Math.max(1, capacity)) * 100));

  return (
    <section className={ui.stack} aria-label="Bookings">
      <div className={ui.card}>
        <div className={ui.spread}>
          <div>
            <h2 className={ui.sectionTitle}>Seats booked</h2>
            <p className={ui.muted}>
              {booked} of {capacity} seats · {confirmed.length} booking{confirmed.length === 1 ? "" : "s"}
            </p>
          </div>
          <strong style={{ fontSize: "1.5rem", letterSpacing: "-0.03em" }}>{fill}%</strong>
        </div>
        <div
          style={{ height: 8, borderRadius: 99, background: "var(--surface-3)", overflow: "hidden", marginTop: 12 }}
          role="progressbar"
          aria-valuenow={fill}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Seats booked"
        >
          <span
            style={{
              display: "block",
              height: "100%",
              width: `${fill}%`,
              borderRadius: 99,
              background: booked > capacity ? "var(--bad)" : fill >= 90 ? "var(--warn)" : "var(--brand)",
            }}
          />
        </div>
      </div>

      {editable && (
        <form className={`${ui.card} ${ui.stack}`} onSubmit={onCreate} aria-label="Add booking">
          <h3 className={ui.sectionTitle}>Add a booking</h3>
          <div className={ui.row}>
            <label className={ui.field}>
              Contact name
              <input name="contact_name" maxLength={120} placeholder="Asha Patil" />
            </label>
            <label className={ui.field} style={{ width: 110 }}>
              Passengers
              <input name="passenger_count" type="number" min={1} max={100} required defaultValue={1} />
            </label>
            {stops.length > 0 || (routeTemplateId && stopList.loading) ? (
              <>
                <label className={ui.field}>
                  Pickup stop
                  <select
                    name="pickup_stop_name"
                    required
                    value={pickup}
                    disabled={stopList.loading}
                    onChange={(event) => setPickup(event.target.value)}
                  >
                    <option value="" disabled>
                      {stopList.loading ? "Loading stops…" : "Choose…"}
                    </option>
                    {stops.slice(0, -1).map((stop) => (
                      <option key={stop.id} value={stop.name}>
                        {stop.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={ui.field}>
                  Drop stop
                  <select name="drop_stop_name" required defaultValue="" key={pickup} disabled={stopList.loading}>
                    <option value="" disabled>
                      {stopList.loading ? "Loading stops…" : "Choose…"}
                    </option>
                    {dropOptions.map((stop) => (
                      <option key={stop.id} value={stop.name}>
                        {stop.name}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            ) : (
              <>
                <label className={ui.field}>
                  Pickup stop
                  <input name="pickup_stop_name" required maxLength={120} />
                </label>
                <label className={ui.field}>
                  Drop stop
                  <input name="drop_stop_name" required maxLength={120} />
                </label>
              </>
            )}
            <label className={ui.field} style={{ flex: 1, minWidth: 200 }}>
              Passenger names (optional)
              <input name="passenger_names" placeholder="Comma separated" />
            </label>
            <button className={ui.button} type="submit" disabled={busy}>
              <Plus size={16} aria-hidden /> Add booking
            </button>
          </div>
          {stops.length === 0 && (
            <p className={ui.hint}>Choose a route option on the Plan tab to pick stops from a list.</p>
          )}
        </form>
      )}

      {editable && (
        <details className={ui.card}>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>Import bookings from a CSV file</summary>
          <form className={ui.row} onSubmit={onImport} aria-label="Import bookings" style={{ marginTop: 14 }}>
            <label className={ui.field}>
              CSV file
              <input name="file" type="file" accept=".csv,text/csv" />
            </label>
            <button className={ui.buttonGhost} type="submit" disabled={busy}>
              <Upload size={15} aria-hidden /> Import
            </button>
            <button className={ui.buttonSoft} type="button" onClick={downloadSample}>
              <Download size={15} aria-hidden /> Sample file
            </button>
            <span className={ui.hint}>Header row: {CSV_HEADER}</span>
          </form>
        </details>
      )}

      {(error ?? loadError) && (
        <p className={ui.error} role="alert" data-testid="bookings-error">
          {error ?? loadError}
        </p>
      )}
      {problems.length > 0 && (
        <ul className={ui.error} style={{ paddingLeft: 30 }}>
          {problems.map((problem) => (
            <li key={`${problem.line}-${problem.error}`}>
              Line {problem.line}: {problem.error}
            </li>
          ))}
        </ul>
      )}
      {loading && <p className={ui.muted}>Loading bookings…</p>}
      {bookings && confirmed.length === 0 && (
        <EmptyState icon={Ticket} title="No bookings yet">
          Add the first booking above, or import a CSV file from your booking system.
        </EmptyState>
      )}

      {bookings && bookings.length > 0 && (
        <div className={ui.stackSm}>
          <label className={ui.checkboxRow}>
            <input type="checkbox" checked={showCancelled} onChange={(event) => setShowCancelled(event.target.checked)} />
            Show cancelled bookings
          </label>
          <div className={ui.tableWrap}>
            <table className={ui.table} aria-label="Bookings">
              <thead>
                <tr>
                  <th>Reference</th>
                  <th>Contact</th>
                  <th>Seats</th>
                  <th>Pickup</th>
                  <th>Drop</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {visible.map((booking) => (
                  <tr key={booking.id}>
                    <td className={ui.mono}>{booking.reference}</td>
                    <td>{booking.contact_name ?? "—"}</td>
                    <td title={booking.passengers.map((p) => p.name).join(", ")}>{booking.passenger_count}</td>
                    <td>{booking.pickup_stop_name}</td>
                    <td>{booking.drop_stop_name}</td>
                    <td>
                      <Pill tone={booking.status === "confirmed" ? "ok" : "neutral"}>{booking.status}</Pill>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {editable && booking.status === "confirmed" && (
                        <button
                          className={`${ui.buttonDanger} ${ui.sm}`}
                          type="button"
                          disabled={busy}
                          onClick={() => run(() => authedRequest(`${base}/${booking.id}`, "DELETE"), "Booking cancelled.")}
                          aria-label={`Cancel booking ${booking.reference}`}
                        >
                          <Trash2 size={14} aria-hidden /> Cancel
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
