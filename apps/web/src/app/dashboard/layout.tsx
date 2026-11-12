import Link from "next/link";
import { redirect } from "next/navigation";
import { connection } from "next/server";
import { Suspense, type ReactNode } from "react";

import { SignOutButton } from "@/components/SignOutButton";
import { createClient } from "@/lib/supabase/server";

import ui from "@/components/ui.module.css";

import styles from "./dashboard.module.css";

/** Reads the session cookie, so it must render inside Suspense (request-time data). */
async function AuthedShell({ children }: { children: ReactNode }) {
  await connection(); // request-time rendering: the session comes from cookies
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <strong>RouteSync</strong>
        <nav className={ui.nav} aria-label="Main">
          <Link href="/dashboard">Overview</Link>
          <Link href="/dashboard/journeys">Journeys</Link>
          <Link href="/dashboard/services">Services</Link>
          <Link href="/dashboard/buses">Buses</Link>
        </nav>
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
