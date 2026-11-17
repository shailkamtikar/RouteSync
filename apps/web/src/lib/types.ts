/** Shapes returned by the operator API, shared by the dashboard screens. */

export type LatLng = { lat: number; lng: number };

export type Service = {
  id: string;
  origin_name: string;
  destination_name: string;
  origin_location: LatLng | null;
  destination_location: LatLng | null;
  status: string;
  route_count?: number;
  shortest_m?: number | null;
  longest_m?: number | null;
  active_journeys?: number;
};

export type Bus = {
  id: string;
  registration: string;
  capacity: number;
  status: string;
  updated_at: string;
};

export type Journey = {
  id: string;
  bus_id: string;
  bus_registration: string;
  bus_capacity: number;
  service_id: string;
  origin_name: string;
  destination_name: string;
  route_template_id: string | null;
  departure_at: string;
  scheduled_arrival_at: string;
  booking_eta_at: string;
  timezone: string;
  status: string;
  manual_mode: boolean;
  plan_needs_review: boolean;
  public_counts_enabled: boolean;
  booked_passengers: number;
};

export type RouteTemplate = {
  id: string;
  name: string;
  version: number;
  status: string;
  distance_m: number | null;
  duration_s: number | null;
  attribution: string | null;
  coordinates: [number, number][];
  stop_count: number;
};

export type RouteStop = {
  id: string;
  name: string;
  location: LatLng;
  chainage_m: number | null;
  kind: "passenger_stop" | "pass_through";
  role: "origin" | "intermediate" | "destination";
  source: string;
};

export const LIVE_STATUSES = ["boarding", "in_progress", "disrupted"];
export const OPEN_STATUSES = ["published", "ready", "boarding", "in_progress", "disrupted"];
export const TIME_ZONE = "Asia/Kolkata";
