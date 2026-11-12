import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiStatus } from "./ApiStatus";

afterEach(() => vi.unstubAllGlobals());

describe("ApiStatus", () => {
  it("shows ok when the API is healthy", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok" }), { status: 200 })),
    );
    render(<ApiStatus />);
    expect(await screen.findByText("API: ok")).toBeInTheDocument();
  });

  it("shows unavailable when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network down")));
    render(<ApiStatus />);
    expect(await screen.findByText("API unavailable")).toBeInTheDocument();
  });

  it("shows unavailable on a non-200 response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 503 })));
    render(<ApiStatus />);
    expect(await screen.findByText("API unavailable")).toBeInTheDocument();
  });

  it("shows unavailable when the body is not ok", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "down" }), { status: 200 })),
    );
    render(<ApiStatus />);
    expect(await screen.findByText("API unavailable")).toBeInTheDocument();
  });
});
