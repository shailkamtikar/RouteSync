"use client";

import { useState, type FormEvent } from "react";

import { authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { useResource } from "@/lib/useResource";

import ui from "./ui.module.css";

type LatLng = { lat: number; lng: number };
export type Service = {
  id: string;
  origin_name: string;
  destination_name: string;
  origin_location: LatLng | null;
  destination_location: LatLng | null;
  status: string;
};

function readPoint(data: FormData, prefix: string): LatLng | null {
  const lat = String(data.get(`${prefix}_lat`) ?? "").trim();
  const lng = String(data.get(`${prefix}_lng`) ?? "").trim();
  if (!lat && !lng) return null;
  return { lat: Number(lat), lng: Number(lng) };
}

function formatPoint(point: LatLng | null): string {
  return point ? `${point.lat.toFixed(4)}, ${point.lng.toFixed(4)}` : "not set";
}

export function ServicesPanel() {
  const {
    data: services,
    error: loadError,
    reload,
    loading,
  } = useResource<Service[]>("/api/v1/services");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
      authedRequest("/api/v1/services", "POST", {
        origin_name: String(data.get("origin_name") ?? ""),
        destination_name: String(data.get("destination_name") ?? ""),
        origin_location: readPoint(data, "origin"),
        destination_location: readPoint(data, "destination"),
      }),
    );
    if (ok) form.reset();
  }

  return (
    <div className={ui.stack}>
      <form className={`${ui.stack} ${ui.card}`} onSubmit={onCreate} aria-label="Add service">
        <div className={ui.row}>
          <label className={ui.field}>
            Origin
            <input name="origin_name" required maxLength={120} placeholder="Pune" />
          </label>
          <label className={ui.field}>
            Origin latitude
            <input name="origin_lat" type="number" step="any" min={-90} max={90} />
          </label>
          <label className={ui.field}>
            Origin longitude
            <input name="origin_lng" type="number" step="any" min={-180} max={180} />
          </label>
        </div>
        <div className={ui.row}>
          <label className={ui.field}>
            Destination
            <input name="destination_name" required maxLength={120} placeholder="Nanded" />
          </label>
          <label className={ui.field}>
            Destination latitude
            <input name="destination_lat" type="number" step="any" min={-90} max={90} />
          </label>
          <label className={ui.field}>
            Destination longitude
            <input name="destination_lng" type="number" step="any" min={-180} max={180} />
          </label>
          <button className={ui.button} type="submit" disabled={busy}>
            Add service
          </button>
        </div>
      </form>

      {(error ?? loadError) && (
        <p className={ui.error} data-testid="panel-error">
          {error ?? loadError}
        </p>
      )}
      {loading && <p className={ui.muted}>Loading services…</p>}
      {services && services.length === 0 && <p className={ui.muted}>No services yet.</p>}

      {services && services.length > 0 && (
        <div className={ui.tableWrap}>
          <table className={ui.table}>
            <thead>
              <tr>
                <th>Service</th>
                <th>Origin point</th>
                <th>Destination point</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {services.map((service) => (
                <tr key={service.id}>
                  <td>
                    {service.origin_name} → {service.destination_name}
                  </td>
                  <td>{formatPoint(service.origin_location)}</td>
                  <td>{formatPoint(service.destination_location)}</td>
                  <td>
                    <button
                      className={ui.buttonDanger}
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        run(() => authedRequest(`/api/v1/services/${service.id}`, "DELETE"))
                      }
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
