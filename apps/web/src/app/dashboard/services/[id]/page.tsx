import type { Metadata } from "next";
import { Suspense } from "react";

import { ServiceDetail } from "@/components/services/ServiceDetail";

export const metadata: Metadata = { title: "Route options" };

async function Detail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ServiceDetail serviceId={id} />;
}

export default function ServiceRoutesPage({ params }: PageProps<"/dashboard/services/[id]">) {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
      <Detail params={params} />
    </Suspense>
  );
}
