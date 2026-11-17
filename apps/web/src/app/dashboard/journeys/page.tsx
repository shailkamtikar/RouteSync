import type { Metadata } from "next";
import { Suspense } from "react";

import { JourneysPanel } from "@/components/journeys/JourneysPanel";

export const metadata: Metadata = { title: "Journeys" };

export default function JourneysPage() {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
      <JourneysPanel />
    </Suspense>
  );
}
