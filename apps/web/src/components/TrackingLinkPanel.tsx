"use client";

import { useState } from "react";

import { authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatInZone } from "@/lib/time";
import { useResource } from "@/lib/useResource";

import type { Journey } from "./JourneysPanel";
import ui from "./ui.module.css";

type LinkStatus = { active: boolean; created_at: string | null; expires_at: string | null };
const LINKABLE = ["ready", "published", "boarding", "in_progress", "disrupted"];

export function TrackingLinkPanel({ journey, onChanged }: { journey: Journey; onChanged: () => void }) {
  const base = `/api/v1/journeys/${journey.id}`;
  const status = useResource<LinkStatus>(`${base}/tracking-link?v=${journey.status}`);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      status.reload();
    } catch (reason) {
      setError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  if (!LINKABLE.includes(journey.status)) return null;
  return (
    <section className={ui.stack} aria-label="Public tracking link">
      <h2>Public tracking link</h2>
      <p className={ui.muted}>
        Anyone with the link sees the bus, route, stops and arrival times. Passenger names and bookings are never shown.
      </p>
      <div className={ui.row}>
        <button
          className={ui.button}
          type="button"
          disabled={busy}
          onClick={() =>
            run(async () => {
              const link = await authedRequest<{ token: string }>(`${base}/tracking-link`, "POST");
              setUrl(`${window.location.origin}/track/${link.token}`);
            })
          }
        >
          {status.data?.active ? "Create new link" : "Create link"}
        </button>
        {status.data?.active && (
          <button
            className={ui.buttonDanger}
            type="button"
            disabled={busy}
            onClick={() =>
              run(async () => {
                await authedRequest(`${base}/tracking-link`, "DELETE");
                setUrl(null);
              })
            }
          >
            Revoke link
          </button>
        )}
        <label className={ui.row}>
          <input
            type="checkbox"
            checked={journey.public_counts_enabled}
            disabled={busy}
            onChange={(event) =>
              run(async () => {
                await authedRequest(`${base}/public-counts`, "PUT", { enabled: event.target.checked });
                onChanged();
              })
            }
          />
          Show passenger counts on the public page
        </label>
      </div>
      {status.data?.active && status.data.expires_at && (
        <p className={ui.muted} data-testid="link-status">
          A link is active until {formatInZone(status.data.expires_at, journey.timezone)}. Creating a new one cancels it.
        </p>
      )}
      {url && (
        <p className={ui.card} data-testid="tracking-url">
          Share this link (shown once): <a href={url}>{url}</a>
        </p>
      )}
      {error && <p className={ui.error}>{error}</p>}
    </section>
  );
}
