"use client";

import { useState, type FormEvent } from "react";

import { authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { useResource } from "@/lib/useResource";

import ui from "./ui.module.css";

export type Bus = {
  id: string;
  registration: string;
  capacity: number;
  status: string;
  updated_at: string;
};

export function BusesPanel() {
  const { data: buses, error: loadError, reload, loading } = useResource<Bus[]>("/api/v1/buses");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      reload();
      return true;
    } catch (reason) {
      setError(describeError(reason));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const ok = await run(() =>
      authedRequest("/api/v1/buses", "POST", {
        registration: String(data.get("registration") ?? ""),
        capacity: Number(data.get("capacity")),
      }),
    );
    if (ok) form.reset();
  }

  async function onSaveCapacity(event: FormEvent<HTMLFormElement>, bus: Bus) {
    event.preventDefault();
    const capacity = Number(new FormData(event.currentTarget).get("capacity"));
    const ok = await run(() =>
      authedRequest(`/api/v1/buses/${bus.id}`, "PATCH", {
        capacity,
        expected_updated_at: bus.updated_at,
      }),
    );
    if (ok) setEditing(null);
  }

  return (
    <div className={ui.stack}>
      <form className={`${ui.row} ${ui.card}`} onSubmit={onCreate} aria-label="Add bus">
        <label className={ui.field}>
          Registration
          <input name="registration" required minLength={4} maxLength={20} placeholder="MH12 AB 1234" />
        </label>
        <label className={ui.field}>
          Capacity
          <input name="capacity" type="number" required min={1} max={100} defaultValue={40} />
        </label>
        <button className={ui.button} type="submit" disabled={busy}>
          Add bus
        </button>
      </form>

      {(error ?? loadError) && (
        <p className={ui.error} data-testid="panel-error">
          {error ?? loadError}
        </p>
      )}
      {loading && <p className={ui.muted}>Loading buses…</p>}
      {buses && buses.length === 0 && <p className={ui.muted}>No buses yet.</p>}

      {buses && buses.length > 0 && (
        <div className={ui.tableWrap}>
          <table className={ui.table}>
            <thead>
              <tr>
                <th>Registration</th>
                <th>Capacity</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {buses.map((bus) => (
                <tr key={bus.id}>
                  <td>{bus.registration}</td>
                  <td>
                    {editing === bus.id ? (
                      <form className={ui.row} onSubmit={(event) => onSaveCapacity(event, bus)}>
                        <label className={ui.field}>
                          <input
                            name="capacity"
                            type="number"
                            min={1}
                            max={100}
                            defaultValue={bus.capacity}
                            aria-label={`Capacity for ${bus.registration}`}
                          />
                        </label>
                        <button className={ui.button} type="submit" disabled={busy}>
                          Save
                        </button>
                      </form>
                    ) : (
                      bus.capacity
                    )}
                  </td>
                  <td className={ui.row}>
                    <button
                      className={ui.buttonGhost}
                      type="button"
                      onClick={() => setEditing(editing === bus.id ? null : bus.id)}
                    >
                      {editing === bus.id ? "Cancel" : "Edit"}
                    </button>
                    <button
                      className={ui.buttonDanger}
                      type="button"
                      disabled={busy}
                      onClick={() => run(() => authedRequest(`/api/v1/buses/${bus.id}`, "DELETE"))}
                    >
                      Remove
                    </button>
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
