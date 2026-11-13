import { describe, expect, it } from "vitest";

import { parseViaPoints } from "./RouteOptionsPanel";

describe("parseViaPoints", () => {
  it("parses named points in order and skips blank lines", () => {
    expect(parseViaPoints("Ahmednagar, 19.0948, 74.7496\n\n  Beed,18.9891,75.7601 ")).toEqual([
      { name: "Ahmednagar", lat: 19.0948, lng: 74.7496 },
      { name: "Beed", lat: 18.9891, lng: 75.7601 },
    ]);
  });

  it("accepts a point without a name and names containing commas", () => {
    expect(parseViaPoints("18.5, 73.8")).toEqual([{ name: null, lat: 18.5, lng: 73.8 }]);
    expect(parseViaPoints("Chowk, Old Town, 18.5, 73.8")[0].name).toBe("Chowk, Old Town");
  });

  it("returns an empty list for empty input", () => {
    expect(parseViaPoints("  \n ")).toEqual([]);
  });

  it("names the bad line", () => {
    expect(() => parseViaPoints("Beed, 18.9, 75.7\nBeed, north, east")).toThrow(/line 2/);
    expect(() => parseViaPoints("Beed")).toThrow(/line 1/);
  });
});
