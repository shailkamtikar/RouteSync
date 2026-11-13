"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import { apiGet, ApiError, API_BASE_URL } from "@/lib/api";
import type { PublicView } from "@/lib/publicTrack";

import styles from "./companion.module.css";

type Turn = { role: "user" | "assistant"; text: string; sources?: Source[]; fallback?: string | null };
type Source = { tool: string; as_of: string | null; availability: string | null };
type ChatOut = { answer: string; sources: Source[]; fallback: string | null };

const MAX_CHARS = 500;
const LIVE_TOOLS = new Set([
  "get_remaining_stops", "get_journey_progress", "get_journey_delay", "get_traffic_summary",
  "get_onboard_passenger_count", "get_stop_status",
]);

export function chipsFor(view: PublicView | null): string[] {
  if (!view) return [];
  const status = view.journey.status;
  if (status === "not_started" || status === "boarding") {
    return ["Where is this bus going?", "Which stops does it make?", "When does it leave?", "What should I do if I'm running late?"];
  }
  if (status === "completed" || status === "cancelled") {
    return ["Which stops did the bus complete?", "How long did the journey take?"];
  }
  const chips = ["How many stops are left?", "Are we running late?", "Is there traffic ahead?", "What happens after the next stop?"];
  if (view.alerts.some((a) => a.type === "delay")) chips.unshift("Why is the bus late?");
  return chips.slice(0, 4);
}

function freshnessNote(sources: Source[] | undefined): string | null {
  if (!sources?.length) return null;
  const live = sources.filter((s) => LIVE_TOOLS.has(s.tool));
  if (!live.length) return null;
  if (live.some((s) => s.availability === "stale")) return "Based on a position that is not live.";
  if (live.some((s) => s.availability === "unknown")) return "Some live details were unavailable.";
  return "Based on live journey data.";
}

export function CompanionPanel({ token, view }: { token: string; view: PublicView | null }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    apiGet<{ enabled: boolean }>(`/api/v1/public/track/${encodeURIComponent(token)}/companion`)
      .then((status) => active && setEnabled(status.enabled))
      .catch(() => active && setEnabled(false));
    return () => {
      active = false;
    };
  }, [token]);

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: "nearest" });
  }, [turns]);

  async function send(question: string) {
    const text = question.trim().slice(0, MAX_CHARS);
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    const history = turns.slice(-6).map((t) => ({ role: t.role, text: t.text }));
    setTurns((current) => [...current, { role: "user", text }]);
    setDraft("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/public/track/${encodeURIComponent(token)}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ question: text, history }),
      });
      if (!response.ok) {
        const detail = (await response.json().catch(() => ({})))?.detail;
        throw new ApiError(response.status, "chat failed", detail);
      }
      const out = (await response.json()) as ChatOut;
      setTurns((current) => [...current, { role: "assistant", text: out.answer, sources: out.sources, fallback: out.fallback }]);
    } catch (reason) {
      const status = reason instanceof ApiError ? reason.status : 0;
      setError(
        status === 429
          ? "Too many questions for now. Please wait a minute."
          : status === 410
            ? "This tracking link is no longer active."
            : "The assistant could not answer right now. The tracking details above are still live.",
      );
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send(draft);
  }

  if (enabled === false) return null;
  return (
    <section className={styles.panel} aria-label="RouteSync Companion" data-testid="companion">
      <h2 className={styles.title}>Ask about this journey</h2>
      <p className={styles.hint}>
        Answers come from this journey&apos;s live data. General advice is marked as such. For booking changes, contact the operator.
      </p>
      <div className={styles.chips}>
        {chipsFor(view).map((chip) => (
          <button key={chip} type="button" className={styles.chip} disabled={busy || enabled === null} onClick={() => send(chip)}>
            {chip}
          </button>
        ))}
      </div>
      <div className={styles.log} role="log" aria-live="polite" data-testid="companion-log">
        {turns.map((turn, index) => (
          <div key={index} className={turn.role === "user" ? styles.user : styles.assistant}>
            <div className={styles.bubble}>{turn.text}</div>
            {turn.role === "assistant" && freshnessNote(turn.sources) && (
              <div className={styles.note}>{freshnessNote(turn.sources)}</div>
            )}
            {turn.role === "assistant" && turn.fallback && turn.fallback !== "scrubbed" && (
              <div className={styles.note}>Assistant unavailable; this is a standard message.</div>
            )}
          </div>
        ))}
        {busy && <div className={styles.assistant}><div className={styles.bubble}>Checking…</div></div>}
        <div ref={bottom} />
      </div>
      {error && (
        <p className={styles.error} role="alert" data-testid="companion-error">
          {error}
        </p>
      )}
      <form className={styles.form} onSubmit={onSubmit}>
        <input
          className={styles.input}
          value={draft}
          onChange={(event) => setDraft(event.target.value.slice(0, MAX_CHARS))}
          placeholder="Ask a question about this journey"
          aria-label="Your question"
          maxLength={MAX_CHARS}
          disabled={busy || enabled === null}
        />
        <span className={styles.counter}>{draft.length}/{MAX_CHARS}</span>
        <button className={styles.send} type="submit" disabled={busy || enabled === null || !draft.trim()}>
          Ask
        </button>
      </form>
    </section>
  );
}
