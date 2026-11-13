import { describe, expect, it } from "vitest";

import { boundsOf, PASS_THROUGH_LABEL, routeFeatures, stopFeatures, type MapStop } from "./mapData";

const route = {
  id: "r1",
  name: "North",
  coordinates: [
    [73.85, 18.52],
    [75.76, 18.99],
    [77.32, 19.14],
  ] as [number, number][],
};

const stops: MapStop[] = [
  { id: "s1", name: "Beed", lng: 75.76, lat: 18.99, kind: "active", status: "next" },
  { id: "s2", name: "Jalna", lng: 75.88, lat: 19.84, kind: "pass_through" },
];

describe("map data", () => {
  it("builds one line per route with default colours and selection", () => {
    const features = routeFeatures([route, { ...route, id: "r2", selected: false }]).features;
    expect(features).toHaveLength(2);
    expect(features[0].properties.selected).toBe(true);
    expect(features[1].properties.selected).toBe(false);
    expect(features[0].properties.color).not.toBe(features[1].properties.color);
  });

  it("skips routes without usable geometry", () => {
    expect(routeFeatures([{ ...route, coordinates: [] }]).features).toEqual([]);
    expect(routeFeatures([{ ...route, coordinates: [[73.85, 18.52]] }]).features).toEqual([]);
    expect(
      routeFeatures([
        {
          ...route,
          coordinates: [
            [Number.NaN, 1],
            [500, 2],
          ],
        },
      ]).features,
    ).toEqual([]);
  });

  it("labels pass-through places as not being passenger stops", () => {
    const features = stopFeatures(stops).features;
    expect(features[0].properties.label).toBe("Beed");
    expect(features[1].properties.label).toContain(PASS_THROUGH_LABEL);
    expect(features[1].properties.kind).toBe("pass_through");
  });

  it("drops stops with invalid coordinates", () => {
    expect(stopFeatures([{ ...stops[0], lat: 123 }]).features).toEqual([]);
  });

  it("computes bounds across route, stops and bus", () => {
    expect(boundsOf([route], stops, { lng: 78, lat: 17, stale: false })).toEqual([
      [73.85, 17],
      [78, 19.84],
    ]);
  });

  it("returns null bounds when there is nothing to show", () => {
    expect(boundsOf([], [], null)).toBeNull();
  });
});
