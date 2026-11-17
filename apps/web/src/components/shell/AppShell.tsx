"use client";

import {
  Bus,
  CalendarClock,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Sun,
  Waypoints,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useSyncExternalStore, type ReactNode } from "react";

import { ToastProvider } from "@/components/kit/Toast";
import { createClient } from "@/lib/supabase/client";
import { useResource } from "@/lib/useResource";

import { Logo } from "./Logo";
import styles from "./shell.module.css";

type Me = { email: string | null; operator_name: string; role: string };

const NAV: { href: string; label: string; icon: LucideIcon; match: (path: string) => boolean }[] = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard, match: (p) => p === "/dashboard" },
  { href: "/dashboard/journeys", label: "Journeys", icon: CalendarClock, match: (p) => p.startsWith("/dashboard/journeys") },
  { href: "/dashboard/services", label: "Services", icon: Waypoints, match: (p) => p.startsWith("/dashboard/services") },
  { href: "/dashboard/buses", label: "Buses", icon: Bus, match: (p) => p.startsWith("/dashboard/buses") },
];

function subscribeTheme(notify: () => void) {
  const observer = new MutationObserver(notify);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  media.addEventListener("change", notify);
  return () => {
    observer.disconnect();
    media.removeEventListener("change", notify);
  };
}

function isDark(): boolean {
  const chosen = document.documentElement.dataset.theme;
  return chosen ? chosen === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function ThemeToggle() {
  const dark = useSyncExternalStore(subscribeTheme, isDark, () => false);
  function toggle() {
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("routesync-theme", next);
    } catch {
      /* private mode: the choice just is not remembered */
    }
  }
  return (
    <button type="button" className={styles.iconBtn} onClick={toggle} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>
      {dark ? <Sun size={17} aria-hidden /> : <Moon size={17} aria-hidden />}
    </button>
  );
}

export function AppShell({ email, children }: { email: string; children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const me = useResource<Me>("/api/v1/me");
  const isMonitor = pathname.endsWith("/monitor");

  async function signOut() {
    await createClient().auth.signOut();
    router.replace("/login");
    router.refresh();
  }

  const initials = (me.data?.operator_name ?? email).slice(0, 2).toUpperCase();

  return (
    <ToastProvider>
      <div className={styles.shell}>
        <button
          type="button"
          className={styles.scrim}
          data-open={open}
          aria-hidden={!open}
          tabIndex={-1}
          onClick={() => setOpen(false)}
        />
        <aside className={styles.sidebar} data-open={open} aria-label="Sidebar">
          <div className={styles.brandRow}>
            <Link href="/dashboard" className={styles.brand}>
              <Logo size={30} />
              <span>RouteSync</span>
            </Link>
            <ThemeToggle />
            <button type="button" className={`${styles.iconBtn} ${styles.closeBtn}`} onClick={() => setOpen(false)} aria-label="Close menu">
              <X size={18} aria-hidden />
            </button>
          </div>
          <nav className={styles.nav} aria-label="Main">
            {NAV.map(({ href, label, icon: Icon, match }) => (
              <Link key={href} href={href} className={styles.navLink} aria-current={match(pathname) ? "page" : undefined} onClick={() => setOpen(false)}>
                <Icon size={18} aria-hidden />
                {label}
              </Link>
            ))}
          </nav>
          <div className={styles.account} data-testid="operator-profile">
            <div className={styles.avatar} aria-hidden>
              {initials}
            </div>
            <div className={styles.accountText}>
              <strong title={me.data?.operator_name}>{me.data?.operator_name ?? "Operator"}</strong>
              <span title={email}>
                {me.data ? `${me.data.role} · ` : ""}
                {email}
              </span>
            </div>
          </div>
          <div className={styles.accountActions}>
            <button type="button" className={styles.signOut} onClick={signOut}>
              <LogOut size={16} aria-hidden /> Sign out
            </button>
          </div>
        </aside>

        <div className={styles.main}>
          <header className={styles.topbar}>
            <button type="button" className={styles.iconBtn} onClick={() => setOpen(true)} aria-label="Open menu">
              <Menu size={20} aria-hidden />
            </button>
            <Link href="/dashboard" className={styles.brand}>
              <Logo size={26} />
              <span>RouteSync</span>
            </Link>
          </header>
          <main className={isMonitor ? styles.contentWide : styles.content} id="content">
            {children}
          </main>
        </div>
      </div>
    </ToastProvider>
  );
}
