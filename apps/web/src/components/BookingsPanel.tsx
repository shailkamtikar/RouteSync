"use client";

import { useState, type FormEvent } from "react";

import { ApiError, authedRequest, authedUpload } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { useResource } from "@/lib/useResource";

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

const CSV_HINT = "reference,contact_name,passenger_count,pickup_stop,drop_stop";

export function BookingsPanel({
  journeyId,
  editable,
  onChanged,
}: {
  journeyId: string;
  editable: boolean;
  onChanged: () => void;
}) {
  const base = `/api/v1/journeys/${journeyId}/bookings`;
  const { data: bookings, error: loadError, reload, loading } = useResource<Booking[]>(base);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<ImportProblem[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<WriteResult | unknown>, done: string) {
    setBusy(true);
    setError(null);
    setProblems([]);
    setNotice(null);
    try {
      const result = (await action()) as Partial<WriteResult> | undefined;
      setNotice(
        result?.capacity_warning
          ? `${done} Total booked passengers now exceed the bus capacity.`
          : done,
      );
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
    if (ok) form.reset();
  }

  async function onImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = new FormData(form).get("file");
    if (!(file instanceof File) || file.size === 0) {
      setError("Choose a CSV file first.");
      return;
    }
    const ok = await run(
      async () => authedUpload(`${base}/import`, await file.text(), "text/csv"),
      "Bookings imported.",
    );
    if (ok) form.reset();
  }

  return (
    <section className={ui.stack} aria-label="Bookings">
      <h2>Bookings</h2>
      {editable && (
        <>
          <form className={`${ui.row} ${ui.card}`} onSubmit={onCreate} aria-label="Add booking">
            <label className={ui.field}>
              Contact name
              <input name="contact_name" maxLength={120} />
            </label>
            <label className={ui.field}>
              Passengers
              <input name="passenger_count" type="number" min={1} max={100} required defaultValue={1} />
            </label>
            <label className={ui.field}>
              Pickup stop
              <input name="pickup_stop_name" required maxLength={120} />
            </label>
            <label className={ui.field}>
              Drop stop
              <input name="drop_stop_name" required maxLength={120} />
            </label>
            <label className={ui.field}>
              Passenger names (optional, comma separated)
              <input name="passenger_names" />
            </label>
            <button className={ui.button} type="submit" disabled={busy}>
              Add booking
            </button>
          </form>
          <form className={`${ui.row} ${ui.card}`} onSubmit={onImport} aria-label="Import bookings">
            <label className={ui.field}>
              Import CSV
              <input name="file" type="file" accept=".csv,text/csv" />
            </label>
            <button className={ui.buttonGhost} type="submit" disabled={busy}>
              Import
            </button>
            <span className={ui.muted}>Header row: {CSV_HINT}</span>
          </form>
        </>
      )}

      {notice && (
        <p className={ui.muted} role="status" data-testid="bookings-notice">
          {notice}
        </p>
      )}
      {(error ?? loadError) && (
        <p className={ui.error} data-testid="bookings-error">
          {error ?? loadError}
        </p>
      )}
      {problems.length > 0 && (
        <ul className={ui.error}>
          {problems.map((problem) => (
            <li key={`${problem.line}-${problem.error}`}>
              Line {problem.line}: {problem.error}
            </li>
          ))}
        </ul>
      )}
      {loading && <p className={ui.muted}>Loading bookings…</p>}
      {bookings && bookings.length === 0 && <p className={ui.muted}>No bookings yet.</p>}

      {bookings && bookings.length > 0 && (
        <div className={ui.tableWrap}>
          <table className={ui.table}>
            <thead>
              <tr>
                <th>Reference</th>
                <th>Contact</th>
                <th>Passengers</th>
                <th>Pickup</th>
                <th>Drop</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {bookings.map((booking) => (
                <tr key={booking.id}>
                  <td>{booking.reference}</td>
                  <td>{booking.contact_name ?? "—"}</td>
                  <td title={booking.passengers.map((p) => p.name).join(", ")}>
                    {booking.passenger_count}
                  </td>
                  <td>{booking.pickup_stop_name}</td>
                  <td>{booking.drop_stop_name}</td>
                  <td>
                    <span className={ui.badge}>{booking.status}</span>
                  </td>
                  <td>
                    {editable && booking.status === "confirmed" && (
                      <button
                        className={ui.buttonDanger}
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          run(
                            () => authedRequest(`${base}/${booking.id}`, "DELETE"),
                            "Booking cancelled.",
                          )
                        }
                      >
                        Cancel booking
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
