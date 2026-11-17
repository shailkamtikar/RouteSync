"use client";

import { Check, Clock, Gauge, MapPin } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { ROUTE_COLORS, type MapRoute, type MapStop } from "@/lib/mapData";
import { formatDuration, km } from "@/lib/time";
import type { Journey, RouteStop, RouteTemplate } from "@/lib/types";
import { useResource } from "@/lib/useResource";

import { useToast } from "./kit/Toast";
import { RouteMap } from "./map/RouteMap";
import ui from "./ui.module.css";
import styles from "./journeys/route.module.css";

/** Shows the route a journey follows and, while it is a draft, lets the operator choose another. */
export function JourneyRoutePanel({ journey, onChanged }: { journey: Journey; onChanged: () => void }) {
  const toast = useToast();
  const templates = useResource<RouteTemplate[]>(
    `/api/v1/services/${journey.service_id}/route-templates?include_archived=true`,
  );
  const stops = useResource<RouteStop[]>(
    journey.route_template_id ? `/api/v1/route-templates/${journey.route_template_id}/stops` : null,
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const current = templates.data?.find((template) => template.id === journey.route_template_id);
  const selectable = (templates.data ?? []).filter((template) => template.status === "ready");
  const isDraft = journey.status === "draft";

  const mapRoutes: MapRoute[] = useMemo(
    () => (current ? [{ id: current.id, name: current.name, coordinates: current.coordinates, color: ROUTE_COLORS[0] }] : []),
    [current],
  );
  const mapStops: MapStop[] = useMemo(
    () =>
      (stops.data ?? []).map((stop) => ({
        id: stop.id,
        name: stop.name,
        lng: stop.location.lng,
        lat: stop.location.lat,
        kind: stop.kind === "pass_through" ? "pass_through" : "active",
        role: stop.role,
      })),
    [stops.data],
  );

  async function choose(template: RouteTemplate) {
    if (template.id === journey.route_template_id) return;
    setBusy(template.id);
    setError(null);
    try {
      await authedRequest(`/api/v1/journeys/${journey.id}/route-template`, "PUT", {
        route_template_id: template.id,
      });
      toast.success(`Following “${template.name}”.`);
      onChanged();
    } catch (reason) {
      setError(describeError(reason));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className={ui.stack} aria-label="Route">
      <div className={ui.spread}>
        <h2 className={ui.sectionTitle}>Route</h2>
        <Link href={`/dashboard/services/${journey.service_id}`} className={ui.link}>
          Manage route options
        </Link>
      </div>
      <p className={ui.muted} data-testid="journey-route">
        {current ? (
          <>
            Following <strong>{current.name}</strong>
            {current.distance_m !== null && ` (${km(current.distance_m)})`}
          </>
        ) : (
          "No route option chosen yet."
        )}
      </p>

      {isDraft && selectable.length > 0 && (
        <ul className={styles.options} aria-label="Route options" role="radiogroup">
          {selectable.map((template, index) => {
            const active = template.id === journey.route_template_id;
            return (
              <li key={template.id}>
                <button
                  type="button"
                  role="radio"
                  aria-checked={active}
                  className={`${styles.option} ${active ? styles.optionActive : ""}`}
                  style={{ ["--accent" as string]: ROUTE_COLORS[index % ROUTE_COLORS.length] }}
                  disabled={busy !== null}
                  onClick={() => choose(template)}
                >
                  <span className={styles.radio} aria-hidden>
                    {active && <Check size={13} />}
                  </span>
                  <span className={styles.text}>
                    <strong>{template.name}</strong>
                    <span className={styles.metrics}>
                      <span>
                        <Gauge size={14} aria-hidden /> {km(template.distance_m)}
                      </span>
                      <span>
                        <Clock size={14} aria-hidden /> {template.duration_s ? formatDuration(template.duration_s) : "—"}
                      </span>
                      <span>
                        <MapPin size={14} aria-hidden /> {template.stop_count} stops
                      </span>
                    </span>
                  </span>
                  {busy === template.id && <span className={ui.small}>Applying…</span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {isDraft && selectable.length === 0 && !templates.loading && (
        <p className={`${ui.notice} ${ui.noticeWarn}`}>
          This service has no ready route option yet.{" "}
          <Link href={`/dashboard/services/${journey.service_id}`} className={ui.link}>
            Add one
          </Link>
        </p>
      )}
      {isDraft && journey.route_template_id && (
        <p className={ui.hint}>Choosing a different route option clears the confirmed stops.</p>
      )}
      {(error ?? templates.error) && (
        <p className={ui.error} role="alert" data-testid="route-error">
          {error ?? templates.error}
        </p>
      )}
      {current && <RouteMap key={current.id} routes={mapRoutes} stops={mapStops} height={380} />}
    </section>
  );
}
