import styles from "./kit.module.css";

type Tone = "neutral" | "info" | "ok" | "warn" | "bad" | "brand" | "violet";

const STATUS: Record<string, { label: string; tone: Tone; live?: boolean }> = {
  draft: { label: "Draft", tone: "neutral" },
  awaiting_confirmation: { label: "Awaiting confirmation", tone: "warn" },
  ready: { label: "Ready", tone: "info" },
  published: { label: "Published", tone: "brand" },
  boarding: { label: "Boarding", tone: "violet", live: true },
  in_progress: { label: "In progress", tone: "ok", live: true },
  completed: { label: "Completed", tone: "neutral" },
  cancelled: { label: "Cancelled", tone: "bad" },
  disrupted: { label: "Disrupted", tone: "bad", live: true },
  // services, route options, buses
  active: { label: "Active", tone: "ok" },
  archived: { label: "Archived", tone: "neutral" },
  ready_route: { label: "Ready", tone: "ok" },
  unresolved: { label: "Not routed", tone: "warn" },
};

export function statusLabel(status: string): string {
  return STATUS[status]?.label ?? status.replaceAll("_", " ");
}

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const entry = STATUS[status] ?? { label: status.replaceAll("_", " "), tone: "neutral" as Tone };
  return (
    <span className={`${styles.status} ${styles[`tone_${entry.tone}`]}`} data-status={status}>
      <span className={`${styles.dot} ${entry.live ? styles.pulse : ""}`} aria-hidden />
      {label ?? entry.label}
    </span>
  );
}

export function Pill({ tone = "neutral", children }: { tone?: Tone; children: React.ReactNode }) {
  return <span className={`${styles.status} ${styles[`tone_${tone}`]}`}>{children}</span>;
}
