"use client";

import { Eye, EyeOff, MapPinned, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Logo } from "@/components/shell/Logo";
import { createClient } from "@/lib/supabase/client";

import styles from "./login.module.css";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    const { error: signInError } = await createClient().auth.signInWithPassword({
      email: String(form.get("email") ?? ""),
      password: String(form.get("password") ?? ""),
    });
    if (signInError) {
      setError("Sign-in failed. Check your email and password.");
      setBusy(false);
      return;
    }
    router.replace("/dashboard");
    router.refresh();
  }

  return (
    <div className={styles.page}>
      <aside className={styles.brand} aria-hidden>
        <Link href="/" className={styles.logo} tabIndex={-1}>
          <Logo size={34} /> RouteSync
        </Link>
        <div className={styles.pitch}>
          <h2>Intelligence behind every journey.</h2>
          <ul>
            <li>
              <MapPinned size={18} /> Every stop served, in order, on the road you approved
            </li>
            <li>
              <Sparkles size={18} /> Reroutes only when the saving is worth it
            </li>
            <li>
              <ShieldCheck size={18} /> Passengers see the bus, never each other
            </li>
          </ul>
        </div>
        <svg className={styles.art} viewBox="0 0 400 260" fill="none">
          <path
            d="M20 220 C 90 200, 80 120, 160 130 S 250 60, 300 80 S 360 40, 380 30"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            strokeDasharray="2 9"
          />
          {[
            [20, 220],
            [160, 130],
            [300, 80],
            [380, 30],
          ].map(([x, y], index) => (
            <circle key={index} cx={x} cy={y} r={index === 3 ? 9 : 6} fill="currentColor" />
          ))}
        </svg>
      </aside>

      <main className={styles.main}>
        <form className={styles.form} onSubmit={onSubmit}>
          <div className={styles.head}>
            <Logo size={40} />
            <h1>Operator sign in</h1>
            <p>Manage your fleet, journeys and live tracking.</p>
          </div>
          <div className={styles.field}>
            <label htmlFor="email">Email</label>
            <input id="email" name="email" type="email" autoComplete="username" required placeholder="you@company.com" />
          </div>
          <div className={styles.field}>
            <label htmlFor="password">Password</label>
            <span className={styles.password}>
              <input
                id="password"
                name="password"
                type={show ? "text" : "password"}
                autoComplete="current-password"
                required
                placeholder="Your password"
              />
              <button
                type="button"
                onClick={() => setShow((value) => !value)}
                aria-label={show ? "Hide password" : "Show password"}
              >
                {show ? <EyeOff size={17} aria-hidden /> : <Eye size={17} aria-hidden />}
              </button>
            </span>
          </div>
          {error && (
            <p role="alert" className={styles.error}>
              {error}
            </p>
          )}
          <button type="submit" className={styles.submit} disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
          <p className={styles.note}>
            Passengers do not need an account: open the tracking link you were sent.
          </p>
        </form>
      </main>
    </div>
  );
}
