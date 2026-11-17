/** Maharashtra place catalog and the named corridors used to suggest route options. */

import corridorData from "@/data/corridors.json";
import placeData from "@/data/places.json";

export type Place = {
  name: string;
  district: string;
  lat: number;
  lng: number;
  tier: number;
  aliases: string[];
};

export type CorridorOption = { name: string; via: string[]; stops: string[] };
export type Corridor = { from: string; to: string; options: CorridorOption[] };

export const PLACES: Place[] = placeData as Place[];
const BY_NAME = new Map(PLACES.map((place) => [place.name.toLowerCase(), place]));
const CORRIDORS = corridorData as Corridor[];

export function findPlace(name: string): Place | undefined {
  return BY_NAME.get(name.trim().toLowerCase());
}

export const point = (place: Place) => ({ lat: place.lat, lng: place.lng });

/** Ranks by how well the query matches the name, an alias (Poona, Aurangabad) or the district. */
export function searchPlaces(query: string, exclude: string[] = [], limit = 8): Place[] {
  const q = query.trim().toLowerCase();
  const skip = new Set(exclude.map((name) => name.toLowerCase()));
  const scored: { place: Place; score: number; order: number }[] = [];
  for (const [order, place] of PLACES.entries()) {
    if (skip.has(place.name.toLowerCase())) continue;
    const name = place.name.toLowerCase();
    const aliases = place.aliases.map((alias) => alias.toLowerCase());
    let score = -1;
    if (!q) score = 10 - place.tier;
    else if (name === q || aliases.includes(q)) score = 100;
    else if (name.startsWith(q)) score = 80;
    else if (aliases.some((alias) => alias.startsWith(q))) score = 70;
    else if (name.split(/\s+/).some((word) => word.startsWith(q))) score = 60;
    else if (name.includes(q) || aliases.some((alias) => alias.includes(q))) score = 40;
    else if (place.district.toLowerCase().startsWith(q)) score = 20;
    if (score >= 0) scored.push({ place, score: score - place.tier * 0.1, order });
  }
  return scored
    .sort((a, b) => b.score - a.score || (q ? a.place.name.localeCompare(b.place.name) : a.order - b.order))
    .slice(0, limit)
    .map((entry) => entry.place);
}

/** Straight-line distance in kilometres. */
export function distanceKm(a: Place, b: Place): number {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLng = (b.lng - a.lng) * rad;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
}

/** Route options known for this origin and destination, in the direction of travel. */
export function suggestOptions(origin: string, destination: string): CorridorOption[] {
  const o = origin.trim().toLowerCase();
  const d = destination.trim().toLowerCase();
  for (const corridor of CORRIDORS) {
    const from = corridor.from.toLowerCase();
    const to = corridor.to.toLowerCase();
    if (from === o && to === d) return corridor.options;
    if (from === d && to === o) {
      return corridor.options.map((option) => ({
        ...option,
        via: [...option.via].reverse(),
        stops: [...option.stops].reverse(),
      }));
    }
  }
  return [];
}

/** A short label for a district-level location, used under place names. */
export const placeLabel = (name: string) => findPlace(name)?.district ?? "";
