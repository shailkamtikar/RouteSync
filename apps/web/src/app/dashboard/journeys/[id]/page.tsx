import { Suspense } from "react";

import { JourneyDetail } from "@/components/JourneyDetail";

async function Detail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <JourneyDetail journeyId={id} />;
}

export default function JourneyPage({ params }: PageProps<"/dashboard/journeys/[id]">) {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
      <Detail params={params} />
    </Suspense>
  );
}
