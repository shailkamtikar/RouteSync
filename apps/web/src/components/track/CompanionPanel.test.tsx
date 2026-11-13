import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PublicView } from "@/lib/publicTrack";

import { chipsFor, CompanionPanel } from "./CompanionPanel";

afterEach(() => vi.unstubAllGlobals());

function view(status: PublicView["journey"]["status"], alerts: PublicView["alerts"] = []): PublicView {
  return {
    schema_version: 1,
    computed_at: "",
    journey: { status, origin_name: "Pune", destination_name: "Nanded", timezone: "Asia/Kolkata", departure_at: "", booking_eta_at: "" },
    route: null,
    bus: null,
    eta: null,
    stops: [],
    pass_through: [],
    alerts,
    counts_enabled: false,
  };
}

describe("suggested questions", () => {
  it("change with the journey state", () => {
    expect(chipsFor(view("not_started"))[0]).toBe("Where is this bus going?");
    expect(chipsFor(view("in_progress"))[0]).toBe("How many stops are left?");
    expect(chipsFor(view("in_progress", [{ type: "delay", severity: "warning", message: "" }]))[0]).toBe("Why is the bus late?");
    expect(chipsFor(view("completed"))).toHaveLength(2);
    expect(chipsFor(null)).toEqual([]);
  });
});

describe("CompanionPanel", () => {
  it("renders nothing when the assistant is disabled", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ enabled: false }), { status: 200 })));
    const { container } = render(<CompanionPanel token="t" view={view("in_progress")} />);
    await vi.waitFor(() => expect(container.querySelector("section")).toBeNull());
  });

  it("escapes anything the assistant returns", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ enabled: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ answer: "<script>alert(1)</script><b>bold</b>", sources: [], fallback: null }), { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    render(<CompanionPanel token="t" view={view("in_progress")} />);
    const chip = await screen.findByRole("button", { name: "How many stops are left?" });
    await vi.waitFor(() => expect(chip).toBeEnabled());
    chip.click();
    const log = await screen.findByTestId("companion-log");
    await vi.waitFor(() => expect(log.textContent).toContain("<script>alert(1)</script>"));
    expect(log.querySelector("script")).toBeNull();
    expect(log.querySelector("b")).toBeNull();
  });
});
