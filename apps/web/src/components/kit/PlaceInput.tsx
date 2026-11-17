"use client";

import { ArrowDown, ArrowUp, MapPin, X } from "lucide-react";
import { useId, useMemo, useRef, useState } from "react";

import { searchPlaces, type Place } from "@/lib/places";

import ui from "../ui.module.css";
import styles from "./kit.module.css";

/** Search-as-you-type picker over the Maharashtra catalog (ARIA combobox, keyboard friendly). */
export function PlaceInput({
  label,
  value,
  onChange,
  exclude = [],
  placeholder = "Search a town or city",
  clearOnPick = false,
  hint,
}: {
  label: string;
  value: Place | null;
  onChange: (place: Place | null) => void;
  exclude?: string[];
  placeholder?: string;
  /** For "add another" pickers: the box empties after a choice. */
  clearOnPick?: boolean;
  hint?: string;
}) {
  const id = useId();
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const shown = open ? text : (value?.name ?? "");

  const excluded = exclude.join("|");
  // eslint-disable-next-line react-hooks/exhaustive-deps -- `excluded` is the stable key of `exclude`
  const results = useMemo(() => searchPlaces(text, exclude, 8), [text, excluded]);

  function pick(place: Place) {
    onChange(place);
    setText("");
    setOpen(false);
    if (clearOnPick) inputRef.current?.focus();
  }

  function onKey(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((index) => Math.min(index + 1, results.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter" && open && results[active]) {
      event.preventDefault();
      pick(results[active]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className={`${ui.field} ${styles.combo}`}>
      <label htmlFor={id}>{label}</label>
      <div style={{ position: "relative" }}>
        <input
          ref={inputRef}
          id={id}
          className={ui.input}
          style={{ width: "100%", paddingLeft: 34 }}
          role="combobox"
          aria-expanded={open}
          aria-controls={`${id}-list`}
          aria-autocomplete="list"
          aria-activedescendant={open && results[active] ? `${id}-${active}` : undefined}
          autoComplete="off"
          placeholder={placeholder}
          value={shown}
          onFocus={() => {
            setText("");
            setOpen(true);
            setActive(0);
          }}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onChange={(event) => {
            setText(event.target.value);
            setOpen(true);
            setActive(0);
            if (value) onChange(null);
          }}
          onKeyDown={onKey}
        />
        <MapPin
          size={16}
          aria-hidden
          style={{ position: "absolute", left: 11, top: 11, color: "var(--text-3)" }}
        />
        {open && (
          <ul className={styles.comboList} id={`${id}-list`} role="listbox" aria-label={label}>
            {results.length === 0 && <li className={styles.comboEmpty}>No Maharashtra place matches “{text}”.</li>}
            {results.map((place, index) => (
              <li
                key={place.name}
                id={`${id}-${index}`}
                role="option"
                aria-selected={index === active}
                className={`${styles.comboItem} ${index === active ? styles.comboItemActive : ""}`}
                onMouseDown={(event) => {
                  event.preventDefault();
                  pick(place);
                }}
                onMouseEnter={() => setActive(index)}
              >
                <span>{place.name}</span>
                <small>{place.district}</small>
              </li>
            ))}
          </ul>
        )}
      </div>
      {hint && <span className={ui.hint}>{hint}</span>}
    </div>
  );
}

/** An ordered list of places the road must pass through. */
export function ViaPicker({
  value,
  onChange,
  exclude,
}: {
  value: Place[];
  onChange: (places: Place[]) => void;
  exclude: string[];
}) {
  const move = (index: number, by: -1 | 1) => {
    const next = [...value];
    const target = index + by;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };
  return (
    <div className={ui.stackSm}>
      <PlaceInput
        label="Add a town the road passes through"
        value={null}
        clearOnPick
        exclude={[...exclude, ...value.map((place) => place.name)]}
        onChange={(place) => place && onChange([...value, place])}
        hint="In travel order. Leave empty for the direct road."
      />
      {value.length > 0 && (
        <ol style={{ listStyle: "none", display: "grid", gap: 6 }} aria-label="Route via">
          {value.map((place, index) => (
            <li
              key={place.name}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "6px 8px 6px 12px",
                border: "1px solid var(--border)",
                borderRadius: 10,
                background: "var(--surface-2)",
              }}
            >
              <span style={{ width: 20, color: "var(--text-3)", fontSize: "0.8rem" }}>{index + 1}</span>
              <span style={{ flex: 1, fontWeight: 600 }}>
                {place.name} <small style={{ color: "var(--text-3)", fontWeight: 450 }}>{place.district}</small>
              </span>
              <button type="button" className={styles.iconButton} onClick={() => move(index, -1)} aria-label={`Move ${place.name} earlier`} disabled={index === 0}>
                <ArrowUp size={15} aria-hidden />
              </button>
              <button type="button" className={styles.iconButton} onClick={() => move(index, 1)} aria-label={`Move ${place.name} later`} disabled={index === value.length - 1}>
                <ArrowDown size={15} aria-hidden />
              </button>
              <button type="button" className={styles.iconButton} onClick={() => onChange(value.filter((p) => p.name !== place.name))} aria-label={`Remove ${place.name}`}>
                <X size={15} aria-hidden />
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
