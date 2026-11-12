"use client";

import { useCallback, useEffect, useState } from "react";

import { authedGet } from "@/lib/api";
import { describeError } from "@/lib/errors";

/** Loads a JSON resource from the API and exposes a reload function. */
export function useResource<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!path) return;
    let active = true;
    authedGet<T>(path)
      .then((value) => {
        if (!active) return;
        setData(value);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (active) setError(describeError(reason));
      });
    return () => {
      active = false;
    };
  }, [path, version]);

  const reload = useCallback(() => setVersion((value) => value + 1), []);
  return { data, error, reload, loading: data === null && error === null };
}
