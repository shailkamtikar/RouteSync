import { Suspense } from "react";

import { MonitorPanel } from "@/components/MonitorPanel";

async function Detail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <MonitorPanel journeyId={id} />;
}

export default function MonitorPage({ params }: PageProps<"/dashboard/journeys/[id]/monitor">) {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
      <Detail params={params} />
    </Suspense>
  );
}
