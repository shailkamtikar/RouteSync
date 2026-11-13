import { apiGet, ApiError } from "@/lib/api";
import type { Commitment, StopEta } from "@/lib/eta";

export type PublicStop = {
  name: string;
  role: string;
  status: "completed" | "current" | "next" | "upcoming";
  eta: string | null;
  departure_eta: string | null;
  remaining_m: number | null;
  lng: number;
  lat: number;
  boarding_count?: number;
  alighting_count?: number;
};

export type PublicView = {
  schema_version: number;
  computed_at: string;
  journey: {
    status: "not_started" | "boarding" | "in_progress" | "completed" | "cancelled";
    origin_name: string;
    destination_name: string;
    timezone: string;
    departure_at: string;
    booking_eta_at: string;
  };
  route: { version: number; coordinates: [number, number][] } | null;
  bus: { lng: number; lat: number; at: string; stale: boolean } | null;
  eta: {
    next_stop: Omit<StopEta, "stop_id">;
    destination: Omit<StopEta, "stop_id">;
    remaining_distance_m: number;
    travelled_distance_m: number;
    progress_pct: number;
    gps_age_s: number | null;
    flags: Record<string, boolean>;
    warnings: { code: string; message: string }[];
    commitment?: Commitment;
  } | null;
  stops: PublicStop[];
  pass_through: { name: string; lng: number; lat: number }[];
  alerts: { type: string; severity: string; message: string }[];
  counts_enabled: boolean;
  onboard?: { method: string; onboard: number | null };
};

export type LinkProblem = "gone" | "unknown" | "unavailable";

export async function fetchPublicView(token: string): Promise<PublicView> {
  return apiGet<PublicView>(`/api/v1/public/track/${encodeURIComponent(token)}`);
}

export function linkProblem(error: unknown): LinkProblem {
  if (error instanceof ApiError) {
    if (error.status === 410) return "gone";
    if (error.status === 404 || error.status === 422) return "unknown";
  }
  return "unavailable";
}
