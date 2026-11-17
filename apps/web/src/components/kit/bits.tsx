"use client";

import { ArrowRight, type LucideIcon } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import styles from "./kit.module.css";

export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
}: {
  icon: LucideIcon;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={styles.empty}>
      <div className={styles.emptyIcon}>
        <Icon size={24} aria-hidden />
      </div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function Skeleton({ height = 16, width = "100%" }: { height?: number; width?: number | string }) {
  const style: CSSProperties = { height, width };
  return <div className={styles.skeleton} style={style} aria-hidden />;
}

export function SkeletonRows({ rows = 4, height = 64 }: { rows?: number; height?: number }) {
  return (
    <div role="status" aria-label="Loading" style={{ display: "grid", gap: 12 }}>
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} height={height} />
      ))}
    </div>
  );
}

type StatTone = "brand" | "ok" | "warn" | "info" | "violet" | "bad";
const TONE: Record<StatTone, string> = {
  brand: "var(--brand-soft)",
  ok: "var(--ok-soft)",
  warn: "var(--warn-soft)",
  info: "var(--info-soft)",
  violet: "var(--violet-soft)",
  bad: "var(--bad-soft)",
};
const TONE_INK: Record<StatTone, string> = {
  brand: "var(--brand)",
  ok: "var(--ok)",
  warn: "var(--warn)",
  info: "var(--info)",
  violet: "var(--violet)",
  bad: "var(--bad)",
};

export function Stat({
  icon: Icon,
  label,
  value,
  tone = "brand",
}: {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  tone?: StatTone;
}) {
  return (
    <div className={styles.stat}>
      <div className={styles.statIcon} style={{ background: TONE[tone], color: TONE_INK[tone] }}>
        <Icon size={20} aria-hidden />
      </div>
      <div>
        <div className={styles.statValue}>{value}</div>
        <div className={styles.statLabel}>{label}</div>
      </div>
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
}: {
  tabs: { id: T; label: string; count?: number }[];
  value: T;
  onChange: (id: T) => void;
  label: string;
}) {
  return (
    <div className={styles.tabs} role="tablist" aria-label={label}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={`tab-${tab.id}`}
          aria-selected={value === tab.id}
          aria-controls={`panel-${tab.id}`}
          className={`${styles.tab} ${value === tab.id ? styles.tabActive : ""}`}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
          {tab.count !== undefined && <span className={styles.tabCount}>{tab.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Chips<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { id: T; label: string; count?: number }[];
  value: T;
  onChange: (id: T) => void;
  label: string;
}) {
  return (
    <div className={styles.segmented} role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          aria-pressed={value === option.id}
          className={`${styles.chip} ${value === option.id ? styles.chipActive : ""}`}
          onClick={() => onChange(option.id)}
        >
          {option.label}
          {option.count !== undefined && <span className={styles.chipCount}>{option.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** "Pune → Nanded" with a quiet arrow. */
export function RouteLabel({ from, to }: { from: string; to: string }) {
  return (
    <span className={styles.route}>
      {from}
      <ArrowRight size={15} aria-hidden />
      <span className={styles.visuallyHidden}> to </span>
      {to}
    </span>
  );
}
