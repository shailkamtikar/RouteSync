import { describe, expect, it } from "vitest";

import { ageText, countdown, delayText, kilometres, type Commitment } from "./eta";

const NOW = Date.parse("2031-03-01T12:00:00Z");
const commitment = (delay: number, status: Commitment["status"]): Commitment => ({
  original_eta: "2031-03-01T18:00:00Z",
  predicted_eta: "2031-03-01T18:00:00Z",
  delay_minutes: delay,
  status,
  is_early: delay < 0,
});

describe("eta formatting", () => {
  it("formats countdowns", () => {
    expect(countdown("2031-03-01T12:12:00Z", NOW)).toBe("12 min");
    expect(countdown("2031-03-01T13:25:00Z", NOW)).toBe("1 h 25 min");
    expect(countdown("2031-03-01T14:05:00Z", NOW)).toBe("2 h 05 min");
    expect(countdown("2031-03-01T11:00:00Z", NOW)).toBe("now");
    expect(countdown(null, NOW)).toBe("—");
  });

  it("formats distances", () => {
    expect(kilometres(431_000)).toBe("431 km");
    expect(kilometres(4_250)).toBe("4.3 km");
    expect(kilometres(0)).toBe("0.0 km");
  });

  it("states delays honestly, early or late", () => {
    expect(delayText(commitment(0.2, "on_time"))).toBe("On time");
    expect(delayText(commitment(-12, "on_time"))).toBe("About 12 min early");
    expect(delayText(commitment(4, "on_time"))).toBe("About 4 min late");
    expect(delayText(commitment(25, "significant"))).toBe("Running 25 min late");
    expect(delayText(commitment(-315, "on_time"))).toBe("About 5 h 15 min early");
    expect(delayText(commitment(90, "significant"))).toBe("Running 1 h 30 min late");
    expect(delayText(undefined)).toBe("");
  });

  it("describes position age", () => {
    expect(ageText(null)).toBe("no position yet");
    expect(ageText(12)).toBe("12 s ago");
    expect(ageText(-3)).toBe("0 s ago");
    expect(ageText(600)).toBe("10 min ago");
    expect(ageText(7200)).toBe("2 h ago");
  });
});
