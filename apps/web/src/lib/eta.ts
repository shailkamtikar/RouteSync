/** Shapes of the ETA snapshot produced by the API, shared by operator and public screens. */

export type StopEta = {
  stop_id: string | null;
  name: string;
  status: "completed" | "current" | "next" | "upcoming";
  eta: string | null;
  departure_eta: string | null;
  remaining_m: number;
  is_destination: boolean;
};

export type Commitment = {
  original_eta: string;
  predicted_eta: string;
  delay_minutes: number;
  status: "on_time" | "minor" | "significant";
  is_early: boolean;
};

export type EtaSnapshot = {
  computed_at: string;
  next_stop: StopEta;
  destination: StopEta;
  stops: StopEta[];
  remaining_distance_m: number;
  travelled_distance_m: number;
  progress_pct: number;
  gps_age_s: number | null;
  flags: Record<string, boolean>;
  warnings: { code: string; message: string }[];
  commitment?: Commitment;
};

/** "1 h 25 min", "12 min", or "now" for a moment in the past. */
export function countdown(iso: string | null, nowMs: number): string {
  if (!iso) return "—";
  const minutes = Math.round((new Date(iso).getTime() - nowMs) / 60_000);
  if (minutes <= 0) return "now";
  const hours = Math.floor(minutes / 60);
  return hours > 0 ? `${hours} h ${String(minutes % 60).padStart(2, "0")} min` : `${minutes} min`;
}

export function kilometres(metres: number): string {
  return metres >= 10_000 ? `${Math.round(metres / 1000)} km` : `${(metres / 1000).toFixed(1)} km`;
}

/** Honest wording for the difference from the arrival promised at booking. */
export function delayText(commitment: Commitment | undefined): string {
  if (!commitment) return "";
  const minutes = Math.round(Math.abs(commitment.delay_minutes));
  if (minutes < 1) return "On time";
  if (commitment.delay_minutes < 0) return `About ${minutes} min early`;
  return commitment.status === "on_time" ? `About ${minutes} min late` : `Running ${minutes} min late`;
}

export function ageText(seconds: number | null): string {
  if (seconds === null) return "no position yet";
  if (seconds < 60) return `${Math.round(seconds)} s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  return `${Math.round(seconds / 3600)} h ago`;
}
