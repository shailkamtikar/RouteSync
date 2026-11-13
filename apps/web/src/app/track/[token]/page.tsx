import type { Metadata } from "next";
import { Suspense } from "react";

import { TrackingPage } from "@/components/track/TrackingPage";

export const metadata: Metadata = {
  title: "Live bus tracking · RouteSync",
  robots: { index: false, follow: false },
};

async function Track({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <TrackingPage token={token} />;
}

export default function PublicTrackPage({ params }: PageProps<"/track/[token]">) {
  return (
    <Suspense fallback={<p role="status">Loading your journey…</p>}>
      <Track params={params} />
    </Suspense>
  );
}
