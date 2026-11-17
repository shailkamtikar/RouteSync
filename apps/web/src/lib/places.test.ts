import { describe, expect, it } from "vitest";

import corridors from "@/data/corridors.json";

import { distanceKm, findPlace, PLACES, searchPlaces, suggestOptions } from "./places";

describe("place catalog", () => {
  it("has unique names and sensible Maharashtra coordinates", () => {
    const names = PLACES.map((place) => place.name.toLowerCase());
    expect(new Set(names).size).toBe(names.length);
    expect(PLACES.length).toBeGreaterThanOrEqual(60);
    for (const place of PLACES) {
      expect(place.lat, place.name).toBeGreaterThan(15.5);
      expect(place.lat, place.name).toBeLessThan(22.2);
      expect(place.lng, place.name).toBeGreaterThan(72.5);
      expect(place.lng, place.name).toBeLessThan(81);
      expect([1, 2, 3]).toContain(place.tier);
    }
  });

  it("only names known places in the corridors, and every pair has at least two roads", () => {
    for (const corridor of corridors) {
      expect(findPlace(corridor.from), corridor.from).toBeDefined();
      expect(findPlace(corridor.to), corridor.to).toBeDefined();
      expect(corridor.options.length, `${corridor.from} to ${corridor.to}`).toBeGreaterThanOrEqual(2);
      for (const option of corridor.options) {
        for (const name of [...option.via, ...option.stops]) expect(findPlace(name), name).toBeDefined();
        expect(option.stops.length).toBeGreaterThan(0);
        // A stop on the way is also a place the road is steered through, or is the route's own town.
        for (const stop of option.stops) expect(option.via, `${option.name}: ${stop}`).toContain(stop);
      }
    }
  });

  it("names the roads of one corridor differently", () => {
    for (const corridor of corridors) {
      const names = corridor.options.map((option) => option.name);
      expect(new Set(names).size).toBe(names.length);
    }
  });
});

describe("searchPlaces", () => {
  it("finds by prefix and ranks an exact match first", () => {
    expect(searchPlaces("pun")[0].name).toBe("Pune");
    expect(searchPlaces("nashik")[0].name).toBe("Nashik");
  });

  it("finds a place by its old name", () => {
    expect(searchPlaces("aurangabad")[0].name).toBe("Chhatrapati Sambhajinagar");
    expect(searchPlaces("ahmednagar")[0].name).toBe("Ahilyanagar");
    expect(searchPlaces("osmanabad")[0].name).toBe("Dharashiv");
  });

  it("matches the start of any word and ignores case and spaces", () => {
    expect(searchPlaces("  SAMBHAJI ")[0].name).toBe("Chhatrapati Sambhajinagar");
  });

  it("offers the biggest hubs when nothing is typed", () => {
    const first = searchPlaces("", [], 5).map((place) => place.name);
    expect(first).toContain("Mumbai");
    expect(first).toContain("Pune");
  });

  it("leaves out excluded places and returns nothing for nonsense", () => {
    expect(searchPlaces("pune", ["Pune"]).map((p) => p.name)).not.toContain("Pune");
    expect(searchPlaces("zzzzqq")).toEqual([]);
  });

  it("limits the number of results", () => {
    expect(searchPlaces("a", [], 3)).toHaveLength(3);
  });
});

describe("distanceKm and suggestOptions", () => {
  it("measures straight-line distance", () => {
    const pune = findPlace("Pune")!;
    const mumbai = findPlace("Mumbai")!;
    expect(distanceKm(pune, mumbai)).toBeGreaterThan(110);
    expect(distanceKm(pune, mumbai)).toBeLessThan(130);
    expect(distanceKm(pune, pune)).toBe(0);
  });

  it("suggests the roads of a known corridor in the direction of travel", () => {
    const forward = suggestOptions("Pune", "Nanded");
    expect(forward).toHaveLength(3);
    expect(forward[0].via[0]).toBe("Ahilyanagar");
    const back = suggestOptions("Nanded", "Pune");
    expect(back).toHaveLength(3);
    expect(back[0].via[back[0].via.length - 1]).toBe("Ahilyanagar");
    expect(back[0].stops).toEqual([...forward[0].stops].reverse());
  });

  it("is case-insensitive and empty for an unknown pair", () => {
    expect(suggestOptions("pune", "NANDED")).toHaveLength(3);
    expect(suggestOptions("Dhule", "Nandurbar")).toEqual([]);
  });
});
