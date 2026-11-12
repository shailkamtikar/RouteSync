/** Typed client for the RouteSync API. Only browser-safe configuration is read here. */

import { createClient } from "@/lib/supabase/client";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...init.headers },
    cache: "no-store",
  });
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = undefined;
    }
    throw new ApiError(response.status, `Request failed with status ${response.status}`, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path);
}

/** Calls an operator endpoint with the signed-in user's access token. */
export async function authedRequest<T>(
  path: string,
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE" = "GET",
  body?: unknown,
): Promise<T> {
  const {
    data: { session },
  } = await createClient().auth.getSession();
  if (!session) throw new ApiError(401, "Not signed in");
  const headers: Record<string, string> = { Authorization: `Bearer ${session.access_token}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  return request<T>(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function authedGet<T>(path: string): Promise<T> {
  return authedRequest<T>(path);
}

export type HealthStatus = { status: string };

export function getHealth(): Promise<HealthStatus> {
  return apiGet<HealthStatus>("/healthz");
}
