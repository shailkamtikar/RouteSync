import type { Metadata } from "next";

import { BusesPanel } from "@/components/buses/BusesPanel";

export const metadata: Metadata = { title: "Buses" };

export default function BusesPage() {
  return <BusesPanel />;
}
