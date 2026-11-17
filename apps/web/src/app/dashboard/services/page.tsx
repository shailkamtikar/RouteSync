import type { Metadata } from "next";

import { ServicesPanel } from "@/components/services/ServicesPanel";

export const metadata: Metadata = { title: "Services" };

export default function ServicesPage() {
  return <ServicesPanel />;
}
