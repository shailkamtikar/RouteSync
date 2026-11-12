"use client";

import { useEffect, useState } from "react";

import { ApiError, authedGet } from "@/lib/api";

type Me = { email: string | null; operator_name: string; role: string };
type State = { kind: "loading" } | { kind: "ready"; me: Me } | { kind: "error"; message: string };

export function OperatorProfile() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    authedGet<Me>("/api/v1/me")
      .then((me) => active && setState({ kind: "ready", me }))
      .catch((error: unknown) => {
        if (!active) return;
        const message =
          error instanceof ApiError && error.status === 403
            ? "Your account is not linked to an operator."
            : "Could not load your operator profile.";
        setState({ kind: "error", message });
      });
    return () => {
      active = false;
    };
  }, []);

  if (state.kind === "loading") return <p role="status">Loading profile…</p>;
  if (state.kind === "error") return <p role="alert">{state.message}</p>;
  return (
    <p data-testid="operator-profile">
      Operator: <strong>{state.me.operator_name}</strong> · Role: <strong>{state.me.role}</strong>
    </p>
  );
}
