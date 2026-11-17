"use client";

import { Check, Copy, ExternalLink, Link2, Lock, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatInZone } from "@/lib/time";
import type { Journey } from "@/lib/types";
import { useResource } from "@/lib/useResource";

import { ConfirmDialog } from "./kit/Modal";
import { Pill } from "./kit/StatusBadge";
import { useToast } from "./kit/Toast";
import ui from "./ui.module.css";

type LinkStatus = { active: boolean; created_at: string | null; expires_at: string | null };
const LINKABLE = ["ready", "published", "boarding", "in_progress", "disrupted"];

export function TrackingLinkPanel({ journey, onChanged }: { journey: Journey; onChanged: () => void }) {
  const toast = useToast();
  const base = `/api/v1/journeys/${journey.id}`;
  const status = useResource<LinkStatus>(`${base}/tracking-link?v=${journey.status}`);
  const [url, setUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [revoking, setRevoking] = useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
      status.reload();
    } catch (reason) {
      toast.failure(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.failure("Could not copy. Select the link and copy it by hand.");
    }
  }

  if (!LINKABLE.includes(journey.status)) {
    return (
      <section className={`${ui.card} ${ui.stackSm}`} aria-label="Public tracking link">
        <h2 className={ui.sectionTitle}>Passenger link</h2>
        <p className={ui.muted}>
          {journey.status === "completed" || journey.status === "cancelled"
            ? "Passenger links close with the journey."
            : "The passenger link becomes available once the route is assigned and the journey is ready."}
        </p>
      </section>
    );
  }

  return (
    <section className={ui.stack} aria-label="Public tracking link">
      <div className={`${ui.card} ${ui.stack}`}>
        <div className={ui.spread}>
          <div>
            <h2 className={ui.sectionTitle}>Passenger link</h2>
            <p className={ui.muted} style={{ maxWidth: "60ch" }}>
              Share one link with the bus. Passengers see the bus, route, stops and honest arrival times. Names and
              bookings are never shown.
            </p>
          </div>
          {status.data?.active ? <Pill tone="ok">Link active</Pill> : <Pill>No active link</Pill>}
        </div>

        <div className={ui.rowCenter}>
          <button
            className={ui.button}
            type="button"
            disabled={busy}
            onClick={() =>
              run(async () => {
                const link = await authedRequest<{ token: string }>(`${base}/tracking-link`, "POST");
                setUrl(`${window.location.origin}/track/${link.token}`);
                toast.success("New passenger link created.");
              })
            }
          >
            <Link2 size={16} aria-hidden /> {status.data?.active ? "Create a new link" : "Create link"}
          </button>
          {status.data?.active && (
            <button className={ui.buttonDanger} type="button" disabled={busy} onClick={() => setRevoking(true)}>
              <Lock size={15} aria-hidden /> Revoke link
            </button>
          )}
        </div>

        {url && (
          <div className={ui.stackSm} data-testid="tracking-url">
            <label className={ui.field}>
              Share this link (shown once)
              <span style={{ display: "flex", gap: 8 }}>
                <input
                  readOnly
                  value={url}
                  onFocus={(event) => event.currentTarget.select()}
                  style={{ flex: 1, fontFamily: "var(--mono)", fontSize: "0.85rem" }}
                  className={ui.input}
                  aria-label="Passenger link"
                />
                <button type="button" className={ui.buttonGhost} onClick={copy}>
                  {copied ? <Check size={15} aria-hidden /> : <Copy size={15} aria-hidden />} {copied ? "Copied" : "Copy"}
                </button>
                <a href={url} target="_blank" rel="noreferrer" className={ui.buttonGhost}>
                  <ExternalLink size={15} aria-hidden /> Open
                </a>
              </span>
            </label>
            <p className={ui.hint}>
              Only a fingerprint of the link is stored, so it cannot be shown again. Create a new link if it is lost.
            </p>
          </div>
        )}
        {status.data?.active && status.data.expires_at && (
          <p className={ui.small} data-testid="link-status">
            A link is active until {formatInZone(status.data.expires_at, journey.timezone)}. Creating a new one cancels
            the old one.
          </p>
        )}
      </div>

      <div className={`${ui.card} ${ui.stackSm}`}>
        <div className={ui.rowCenter}>
          <ShieldCheck size={18} aria-hidden style={{ color: "var(--ok)" }} />
          <h3 className={ui.sectionTitle}>Privacy</h3>
        </div>
        <label className={ui.checkboxRow}>
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
        <p className={ui.hint}>Counts are totals only. No names, phone numbers or seat numbers are ever published.</p>
      </div>

      <ConfirmDialog
        open={revoking}
        title="Revoke the passenger link?"
        message="Anyone who has the link will see that it is no longer available. You can create a new one at any time."
        confirmLabel="Revoke link"
        busy={busy}
        onCancel={() => setRevoking(false)}
        onConfirm={() =>
          run(async () => {
            await authedRequest(`${base}/tracking-link`, "DELETE");
            setUrl(null);
            setRevoking(false);
            toast.success("Link revoked.");
          })
        }
      />
    </section>
  );
}
