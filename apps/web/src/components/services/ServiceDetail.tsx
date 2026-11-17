"use client";

import { Clock, Gauge, MapPin, Plus, RefreshCw, Route as RouteIcon, Sparkles, Trash2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import { EmptyState, RouteLabel, SkeletonRows } from "@/components/kit/bits";
import { ConfirmDialog, Modal } from "@/components/kit/Modal";
import { PageHeader } from "@/components/kit/PageHeader";
import { PlaceInput, ViaPicker } from "@/components/kit/PlaceInput";
import { Pill, StatusBadge } from "@/components/kit/StatusBadge";
import { useToast } from "@/components/kit/Toast";
import { RouteMap } from "@/components/map/RouteMap";
import { ApiError, authedGet, authedRequest } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { ROUTE_COLORS, type MapRoute, type MapStop } from "@/lib/mapData";
import { point, suggestOptions, type CorridorOption, type Place } from "@/lib/places";
import { addCorridorOption, type WriteResult } from "@/lib/routeOptions";
import { formatDuration, km } from "@/lib/time";
import type { RouteStop, RouteTemplate, Service } from "@/lib/types";
import { useResource } from "@/lib/useResource";

import ui from "../ui.module.css";
import styles from "./detail.module.css";

type Candidate = { name: string; location: { lat: number; lng: number }; place_type: string; chainage_m: number };
type Candidates = { available: boolean; message: string | null; candidates: Candidate[] };

function nameFromVia(via: Place[]): string {
  if (via.length === 0) return "Direct road";
  const names = via.map((place) => place.name);
  return `Via ${names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`}`;
}

export function ServiceDetail({ serviceId }: { serviceId: string }) {
  const toast = useToast();
  const service = useResource<Service>(`/api/v1/services/${serviceId}`);
  const templates = useResource<RouteTemplate[]>(`/api/v1/services/${serviceId}/route-templates`);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = templates.data?.find((t) => t.id === selectedId) ?? templates.data?.[0] ?? null;
  const stops = useResource<RouteStop[]>(selected ? `/api/v1/route-templates/${selected.id}/stops` : null);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<RouteTemplate | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const suggested = useMemo(() => {
    if (!service.data) return [];
    const have = new Set((templates.data ?? []).map((t) => t.name.toLowerCase()));
    return suggestOptions(service.data.origin_name, service.data.destination_name).filter(
      (option) => !have.has(option.name.toLowerCase()),
    );
  }, [service.data, templates.data]);

  const mapRoutes: MapRoute[] = useMemo(
    () =>
      (templates.data ?? []).map((template, index) => ({
        id: template.id,
        name: template.name,
        coordinates: template.coordinates,
        color: ROUTE_COLORS[index % ROUTE_COLORS.length],
        selected: template.id === selected?.id,
      })),
    [templates.data, selected?.id],
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

  async function act(key: string, action: () => Promise<void>) {
    setBusy(key);
    try {
      await action();
    } catch (reason) {
      toast.failure(reason instanceof Error && !(reason instanceof ApiError) ? reason.message : describeError(reason));
    } finally {
      setBusy(null);
    }
  }

  const addSuggested = (option: CorridorOption) =>
    act(`suggest:${option.name}`, async () => {
      const result = await addCorridorOption(serviceId, option);
      if (result.generation_error) toast.failure(`Saved, but the road could not be drawn: ${result.generation_error}`);
      else toast.success(`Added “${option.name}”.`);
      setSelectedId(result.template.id);
      templates.reload();
    });

  const loadError = service.error ?? templates.error;

  if (service.loading && !service.error) return <SkeletonRows rows={3} height={120} />;
  if (service.error)
    return (
      <div className={ui.stack}>
        <PageHeader title="Service not found" back={{ href: "/dashboard/services", label: "Services" }} />
        <p className={ui.error} role="alert">
          {service.error}
        </p>
      </div>
    );
  const svc = service.data!;

  return (
    <div className={ui.stack}>
      <PageHeader
        back={{ href: "/dashboard/services", label: "Services" }}
        title={<RouteLabel from={svc.origin_name} to={svc.destination_name} />}
        subtitle={
          templates.data
            ? `${templates.data.length} route option${templates.data.length === 1 ? "" : "s"}. Journeys on this service follow one of them.`
            : undefined
        }
        actions={
          <button type="button" className={ui.button} onClick={() => setAdding(true)}>
            <Plus size={16} aria-hidden /> Add route option
          </button>
        }
      />
      {(!svc.origin_location || !svc.destination_location) && (
        <p className={ui.error}>This service has no origin or destination coordinates, so routes cannot be generated.</p>
      )}
      {loadError && (
        <p className={ui.error} role="alert" data-testid="routes-error">
          {loadError}
        </p>
      )}

      <div className={styles.layout}>
        <div className={styles.mapCol}>
          <RouteMap
            routes={mapRoutes}
            stops={mapStops}
            height="100%"
            label="Route options map"
            fitKey={selected?.id}
            onRouteClick={setSelectedId}
          />
        </div>

        <div className={styles.listCol}>
          {templates.loading && <SkeletonRows rows={2} height={110} />}
          {templates.data?.length === 0 && (
            <EmptyState icon={RouteIcon} title="No route options yet">
              Add the road this service takes, for example the highway through the towns you serve.
            </EmptyState>
          )}

          {suggested.length > 0 && (
            <section className={styles.suggest} aria-label="Suggested route options">
              <div className={styles.suggestHead}>
                <Sparkles size={16} aria-hidden />
                <strong>Known corridors for this pair</strong>
              </div>
              <ul>
                {suggested.map((option) => (
                  <li key={option.name}>
                    <span>{option.name}</span>
                    <button
                      type="button"
                      className={`${ui.buttonSoft} ${ui.sm}`}
                      disabled={busy !== null}
                      onClick={() => addSuggested(option)}
                    >
                      {busy === `suggest:${option.name}` ? "Drawing…" : "Add"}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <ul className={styles.options} aria-label="Route options">
            {templates.data?.map((template, index) => {
              const isSelected = template.id === selected?.id;
              return (
                <li
                  key={template.id}
                  className={`${styles.option} ${isSelected ? styles.optionActive : ""}`}
                  style={{ ["--accent" as string]: ROUTE_COLORS[index % ROUTE_COLORS.length] }}
                  data-testid="route-option"
                  aria-current={isSelected}
                >
                  <button
                    type="button"
                    className={styles.optionMain}
                    onClick={() => setSelectedId(template.id)}
                    aria-pressed={isSelected}
                  >
                    <span className={styles.swatch} aria-hidden />
                    <span className={styles.optionText}>
                      <strong>
                        {template.name}
                        {template.version > 1 ? ` (v${template.version})` : ""}
                      </strong>
                      <span className={styles.metrics}>
                        <span>
                          <Gauge size={14} aria-hidden /> {km(template.distance_m)}
                        </span>
                        <span>
                          <Clock size={14} aria-hidden />{" "}
                          {template.duration_s === null ? "—" : formatDuration(template.duration_s)}
                        </span>
                        <span>
                          <MapPin size={14} aria-hidden /> {template.stop_count} stops
                        </span>
                      </span>
                    </span>
                    <StatusBadge
                      status={template.status === "ready" ? "ready_route" : template.status}
                    />
                  </button>
                  <div className={styles.optionActions}>
                    {template.status === "unresolved" && (
                      <button
                        type="button"
                        className={`${ui.buttonGhost} ${ui.sm}`}
                        disabled={busy !== null}
                        onClick={() =>
                          act(`gen:${template.id}`, async () => {
                            await authedRequest(`/api/v1/route-templates/${template.id}/generate`, "POST");
                            templates.reload();
                          })
                        }
                      >
                        <RefreshCw size={14} aria-hidden /> Draw road
                      </button>
                    )}
                    <button
                      type="button"
                      className={`${ui.buttonDanger} ${ui.sm}`}
                      disabled={busy !== null}
                      onClick={() => setRemoving(template)}
                      aria-label={`Remove ${template.name}`}
                    >
                      <Trash2 size={14} aria-hidden /> Remove
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>

          {selected && selected.status === "ready" && (
            <StopsEditor
              key={selected.id}
              template={selected}
              stops={stops.data}
              loading={stops.loading}
              onChanged={() => {
                stops.reload();
                templates.reload();
              }}
            />
          )}
        </div>
      </div>

      <AddRouteDialog
        open={adding}
        service={svc}
        onClose={() => setAdding(false)}
        onCreated={(result) => {
          setAdding(false);
          setSelectedId(result.template.id);
          templates.reload();
          if (result.generation_error) toast.failure(`Saved, but the road could not be drawn: ${result.generation_error}`);
          else toast.success(`Added “${result.template.name}”.`);
        }}
      />
      <ConfirmDialog
        open={removing !== null}
        title="Remove this route option?"
        message={
          removing && (
            <>
              <strong>{removing.name}</strong> and its stops will be removed. Journeys already using it keep their plan.
            </>
          )
        }
        confirmLabel="Remove route option"
        busy={busy === "remove"}
        onCancel={() => setRemoving(null)}
        onConfirm={() =>
          removing &&
          act("remove", async () => {
            await authedRequest(`/api/v1/route-templates/${removing.id}`, "DELETE");
            toast.success(`Removed “${removing.name}”.`);
            setRemoving(null);
            setSelectedId(null);
            templates.reload();
          })
        }
      />
    </div>
  );
}

function AddRouteDialog({
  open,
  service,
  onClose,
  onCreated,
}: {
  open: boolean;
  service: Service;
  onClose: () => void;
  onCreated: (result: WriteResult) => void;
}) {
  const [via, setVia] = useState<Place[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const effectiveName = name.trim() || nameFromVia(via);

  function close() {
    if (busy) return;
    setVia([]);
    setName("");
    setError(null);
    onClose();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await authedRequest<WriteResult>(`/api/v1/services/${service.id}/route-templates`, "POST", {
        name: effectiveName,
        via_points: via.map((place) => ({ name: place.name, ...point(place) })),
      });
      setVia([]);
      setName("");
      onCreated(result);
    } catch (reason) {
      setError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="Add route option"
      description={`A different road for ${service.origin_name} to ${service.destination_name}. Choose the towns it passes through.`}
    >
      <form className={ui.stack} onSubmit={submit} aria-label="New route option">
        <ViaPicker value={via} onChange={setVia} exclude={[service.origin_name, service.destination_name]} />
        <label className={ui.field}>
          Name
          <input
            name="name"
            maxLength={120}
            value={name}
            placeholder={nameFromVia(via)}
            onChange={(event) => setName(event.target.value)}
          />
          <span className={ui.hint}>Leave empty to use “{nameFromVia(via)}”.</span>
        </label>
        {error && (
          <p className={ui.error} role="alert">
            {error}
          </p>
        )}
        <div className={ui.rowCenter} style={{ justifyContent: "flex-end" }}>
          <button type="button" className={ui.buttonGhost} onClick={close} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className={ui.button} disabled={busy}>
            {busy ? "Drawing the road…" : "Create route option"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function StopsEditor({
  template,
  stops,
  loading,
  onChanged,
}: {
  template: RouteTemplate;
  stops: RouteStop[] | null;
  loading: boolean;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [place, setPlace] = useState<Place | null>(null);
  const [kind, setKind] = useState<"passenger_stop" | "pass_through">("passenger_stop");
  const [candidates, setCandidates] = useState<Candidates | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } catch (reason) {
      toast.failure(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  const addStop = (name: string, location: { lat: number; lng: number }, stopKind: RouteStop["kind"], source: string) =>
    run(async () => {
      await authedRequest(`/api/v1/route-templates/${template.id}/stops`, "POST", {
        name,
        location,
        kind: stopKind,
        source,
      });
      toast.success(`${name} added.`);
      setCandidates((current) =>
        current ? { ...current, candidates: current.candidates.filter((c) => c.name !== name) } : current,
      );
      onChanged();
    });

  function onAdd(event: FormEvent) {
    event.preventDefault();
    if (!place) return;
    void addStop(place.name, point(place), kind, "operator").then(() => setPlace(null));
  }

  return (
    <section className={styles.stops} aria-label="Stops">
      <div className={ui.spread}>
        <h2 className={ui.sectionTitle}>Stops on this route</h2>
        <span className={ui.small}>These belong to this route option only.</span>
      </div>
      {loading && <SkeletonRows rows={3} height={44} />}
      <ol className={styles.timeline} aria-label="Route stops" data-testid="route-stops">
        {stops?.map((stop) => (
          <li key={stop.id} data-role={stop.role} data-kind={stop.kind}>
            <span className={styles.node} aria-hidden />
            <div className={styles.stopText}>
              <strong>{stop.name}</strong>
              <small>
                {stop.chainage_m === null ? "" : `${km(stop.chainage_m)} from the start · `}
                {stop.role !== "intermediate"
                  ? stop.role === "origin"
                    ? "Origin"
                    : "Destination"
                  : stop.kind === "pass_through"
                    ? "No passenger stop"
                    : "Passenger stop"}
              </small>
            </div>
            {stop.kind === "pass_through" && stop.role === "intermediate" && <Pill>Label only</Pill>}
            {stop.role === "intermediate" && (
              <button
                type="button"
                className={styles.iconDanger}
                disabled={busy}
                aria-label={`Remove stop ${stop.name}`}
                onClick={() =>
                  run(async () => {
                    await authedRequest(`/api/v1/route-template-stops/${stop.id}`, "DELETE");
                    onChanged();
                  })
                }
              >
                <Trash2 size={15} aria-hidden />
              </button>
            )}
          </li>
        ))}
      </ol>

      <form className={styles.addStop} onSubmit={onAdd} aria-label="Add stop">
        <PlaceInput
          label="Add a stop"
          value={place}
          onChange={setPlace}
          exclude={(stops ?? []).map((s) => s.name)}
          placeholder="Town on this road"
          hint="The stop must lie on this road. We check it for you."
        />
        <label className={ui.field}>
          Type
          <select value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}>
            <option value="passenger_stop">Passenger stop</option>
            <option value="pass_through">Map label only</option>
          </select>
        </label>
        <button className={ui.button} type="submit" disabled={busy || !place}>
          <Plus size={16} aria-hidden /> Add stop
        </button>
      </form>

      <div className={ui.rowCenter}>
        <button
          type="button"
          className={ui.buttonGhost}
          disabled={busy}
          onClick={() =>
            run(async () => {
              setCandidates(await authedGet<Candidates>(`/api/v1/route-templates/${template.id}/stop-candidates`));
            })
          }
        >
          <Sparkles size={15} aria-hidden /> Find more places along this road
        </button>
        <span className={ui.small}>Suggestions from OpenStreetMap become stops only when you add them.</span>
      </div>
      {candidates && !candidates.available && <p className={ui.notice}>{candidates.message}</p>}
      {candidates?.available && candidates.candidates.length === 0 && (
        <p className={ui.muted}>No further places found along this route.</p>
      )}
      {candidates?.available && candidates.candidates.length > 0 && (
        <ul className={styles.candidates} aria-label="Suggested places">
          {candidates.candidates.map((candidate) => (
            <li key={candidate.name}>
              <span>
                <strong>{candidate.name}</strong>
                <small>
                  {candidate.place_type} · {km(candidate.chainage_m)} along
                </small>
              </span>
              <span className={ui.rowCenter}>
                <button
                  type="button"
                  className={`${ui.buttonSoft} ${ui.sm}`}
                  disabled={busy}
                  onClick={() => addStop(candidate.name, candidate.location, "passenger_stop", "osm")}
                >
                  Passenger stop
                </button>
                <button
                  type="button"
                  className={`${ui.buttonGhost} ${ui.sm}`}
                  disabled={busy}
                  onClick={() => addStop(candidate.name, candidate.location, "pass_through", "osm")}
                >
                  Label only
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {template.attribution && <p className={ui.small}>Route data: {template.attribution}</p>}
    </section>
  );
}

