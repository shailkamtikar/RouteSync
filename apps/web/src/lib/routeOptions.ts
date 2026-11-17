/** Creating route options (and their stops) from the corridor catalog. */

import { authedRequest } from "@/lib/api";
import { findPlace, point, type CorridorOption } from "@/lib/places";
import type { RouteTemplate } from "@/lib/types";

export type WriteResult = {
  template: RouteTemplate;
  generation_error: string | null;
  warnings: string[];
};

/** Creates one route option through the named towns and confirms its stops. */
export async function addCorridorOption(
  serviceId: string,
  option: CorridorOption,
): Promise<WriteResult> {
  const via = option.via.flatMap((name) => {
    const place = findPlace(name);
    return place ? [{ name: place.name, ...point(place) }] : [];
  });
  const created = await authedRequest<WriteResult>(
    `/api/v1/services/${serviceId}/route-templates`,
    "POST",
    { name: option.name, via_points: via },
  );
  if (created.generation_error) return created;
  for (const name of option.stops) {
    const place = findPlace(name);
    if (!place) continue;
    await authedRequest(`/api/v1/route-templates/${created.template.id}/stops`, "POST", {
      name: place.name,
      location: point(place),
    });
  }
  return created;
}
