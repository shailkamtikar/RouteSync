"use client";

import { useEffect, useState } from "react";

import { getHealth } from "@/lib/api";

type State = "checking" | "ok" | "unavailable";

const LABELS: Record<State, string> = {
  checking: "API: checking…",
  ok: "API: ok",
  unavailable: "API unavailable",
};

export function ApiStatus() {
  const [state, setState] = useState<State>("checking");

  useEffect(() => {
    let active = true;
    getHealth()
      .then((health) => {
        if (active) setState(health.status === "ok" ? "ok" : "unavailable");
      })
      .catch(() => {
        if (active) setState("unavailable");
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <p role="status" data-state={state}>
      {LABELS[state]}
    </p>
  );
}
