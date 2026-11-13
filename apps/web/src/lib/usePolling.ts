"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { describeError } from "@/lib/errors";

/**
 * Polls `load` every `intervalMs`. Pauses while the tab is hidden, backs off after errors
 * (up to 30 s) and keeps showing the last good data while reconnecting.
 */
export function usePolling<T>(load: () => Promise<T>, intervalMs: number, enabled = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const loadRef = useRef(load);
  const tick = useRef<() => void>(() => {});

  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;

    const run = async () => {
      if (!active) return;
      if (document.hidden) {
        timer = setTimeout(run, intervalMs);
        return;
      }
      try {
        const value = await loadRef.current();
        if (!active) return;
        failures = 0;
        setData(value);
        setError(null);
        setUpdatedAt(Date.now());
      } catch (reason) {
        if (!active) return;
        failures += 1;
        setError(describeError(reason));
      }
      const delay = Math.min(intervalMs * 2 ** Math.min(failures, 4), 30_000);
      timer = setTimeout(run, failures ? delay : intervalMs);
    };
    tick.current = () => {
      clearTimeout(timer);
      void run();
    };
    void run();
    const onVisible = () => {
      if (!document.hidden) tick.current();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      active = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [intervalMs, enabled]);

  const refresh = useCallback(() => tick.current(), []);
  return { data, error, updatedAt, refresh };
}
