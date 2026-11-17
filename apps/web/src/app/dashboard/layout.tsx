import { redirect } from "next/navigation";
import { connection } from "next/server";
import { Suspense, type ReactNode } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { createClient } from "@/lib/supabase/server";

/** Reads the session cookie, so it must render inside Suspense (request-time data). */
async function AuthedShell({ children }: { children: ReactNode }) {
  await connection(); // request-time rendering: the session comes from cookies
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  return <AppShell email={user.email ?? ""}>{children}</AppShell>;
}

export default function DashboardLayout({ children }: LayoutProps<"/dashboard">) {
  return (
    <Suspense fallback={<p role="status" style={{ padding: 24 }}>Loading…</p>}>
      <AuthedShell>{children}</AuthedShell>
    </Suspense>
  );
}
