import { describe, expect, it } from "vitest";

import { formatClock, formatDay, formatDuration, formatInZone, km, zonedInputToIso } from "./time";

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

describe("formatDay and km", () => {
  const now = new Date("2026-11-17T10:00:00Z"); // 15:30 on 17 Nov in India

  it("says today, tomorrow and yesterday in the journey's zone", () => {
    expect(formatDay("2026-11-17T12:30:00Z", "Asia/Kolkata", now)).toBe("Today 18:00");
    expect(formatDay("2026-11-18T01:00:00Z", "Asia/Kolkata", now)).toBe("Tomorrow 06:30");
    expect(formatDay("2026-11-16T16:00:00Z", "Asia/Kolkata", now)).toBe("Yesterday 21:30");
  });

  it("uses the date for other days", () => {
    expect(formatDay("2026-11-25T03:30:00Z", "Asia/Kolkata", now)).toBe("25 Nov, 09:00");
  });

  it("decides the day in the zone, not in UTC", () => {
    // 20:00 UTC on the 17th is already 01:30 on the 18th in India.
    expect(formatDay("2026-11-17T20:00:00Z", "Asia/Kolkata", now)).toBe("Tomorrow 01:30");
  });

  it("rounds kilometres and handles a missing distance", () => {
    expect(km(458_400)).toBe("458 km");
    expect(km(null)).toBe("—");
    expect(km(undefined)).toBe("—");
  });
});
