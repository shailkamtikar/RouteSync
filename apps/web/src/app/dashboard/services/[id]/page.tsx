import { Suspense } from "react";

import { RouteOptionsPanel } from "@/components/RouteOptionsPanel";

async function Detail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RouteOptionsPanel serviceId={id} />;
}

export default function ServiceRoutesPage({ params }: PageProps<"/dashboard/services/[id]">) {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
      <Detail params={params} />
    </Suspense>
  );
}
