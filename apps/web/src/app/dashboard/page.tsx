import type { Metadata } from "next";

import { OverviewPanel } from "@/components/overview/OverviewPanel";

export const metadata: Metadata = { title: "Overview" };

export default function DashboardPage() {
  return <OverviewPanel />;
}
