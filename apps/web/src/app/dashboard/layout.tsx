import { redirect } from "next/navigation";
import { Suspense, type ReactNode } from "react";

import { SignOutButton } from "@/components/SignOutButton";
import { createClient } from "@/lib/supabase/server";

import styles from "./dashboard.module.css";

/** Reads the session cookie, so it must render inside Suspense (request-time data). */
async function AuthedShell({ children }: { children: ReactNode }) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <strong>RouteSync</strong>
        <span className={styles.spacer} />
        <span className={styles.email}>{user.email}</span>
        <SignOutButton />
      </header>
      <main className={styles.content}>{children}</main>
    </div>
  );
}

export default function DashboardLayout({ children }: LayoutProps<"/dashboard">) {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
      <AuthedShell>{children}</AuthedShell>
    </Suspense>
  );
}
