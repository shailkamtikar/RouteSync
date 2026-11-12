import { describe, expect, it } from "vitest";

import { formatClock, formatDuration, formatInZone, zonedInputToIso } from "./time";

describe("time helpers", () => {
  it("converts an India wall-clock time to UTC", () => {
    expect(zonedInputToIso("2031-03-01T22:00", "Asia/Kolkata")).toBe("2031-03-01T16:30:00.000Z");
  });

  it("converts a UTC wall-clock time unchanged", () => {
    expect(zonedInputToIso("2031-03-01T22:00", "UTC")).toBe("2031-03-01T22:00:00.000Z");
  });

  it("handles a zone behind UTC across midnight", () => {
    expect(zonedInputToIso("2031-01-01T20:00", "America/New_York")).toBe(
      "2031-01-02T01:00:00.000Z",
    );
  });

  it("rejects an invalid value", () => {
    expect(() => zonedInputToIso("not-a-date", "UTC")).toThrow();
  });

  it("formats an instant in the journey time zone", () => {
    expect(formatInZone("2031-03-01T16:30:00Z", "Asia/Kolkata")).toBe("1 Mar 2031, 22:00");
    expect(formatClock("2031-03-01T16:30:00Z", "Asia/Kolkata")).toBe("22:00");
  });

  it("formats durations", () => {
    expect(formatDuration(7500)).toBe("2 h 05 min");
    expect(formatDuration(300)).toBe("5 min");
    expect(formatDuration(-5)).toBe("0 min");
  });
});
