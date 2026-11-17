import { ArrowRight, Bus, MapPinned, MessagesSquare, RouteIcon, ShieldCheck, Timer } from "lucide-react";
import Link from "next/link";

import { ApiStatus } from "@/components/ApiStatus";
import { Logo } from "@/components/shell/Logo";

import styles from "./page.module.css";

const FEATURES = [
  {
    icon: RouteIcon,
    title: "Routes that keep their promises",
    text: "Every confirmed stop is served, in order, on a road corridor you approved. Nothing is added, nothing is skipped.",
  },
  {
    icon: Timer,
    title: "Honest arrival times",
    text: "Passengers see the arrival promised at booking beside a live prediction, and a plain note when the bus runs late.",
  },
  {
    icon: Bus,
    title: "Reroutes only when worth it",
    text: "Whole-journey candidates are scored. A change needs a clear saving, confirmed twice, and every decision is logged.",
  },
  {
    icon: MapPinned,
    title: "A tracking page, not an app",
    text: "One unguessable, revocable link. Live map, stop timeline and pass-through towns clearly marked. No account, no install.",
  },
  {
    icon: MessagesSquare,
    title: "An assistant that knows one journey",
    text: "Questions are answered from that journey's live data only, with the arithmetic done by the backend.",
  },
  {
    icon: ShieldCheck,
    title: "Private by construction",
    text: "Passenger names and bookings never reach the public page. Operators only ever see their own data.",
  },
];

export default function Home() {
  return (
    <div className={styles.page}>
      <header className={styles.nav}>
        <Link href="/" className={styles.brand}>
          <Logo size={30} /> RouteSync
        </Link>
        <Link href="/login" className={styles.navCta}>
          Operator sign in
        </Link>
      </header>

      <main>
        <section className={styles.hero}>
          <p className={styles.kicker}>Bus journey management for Maharashtra and beyond</p>
          <h1>Intelligence behind every journey.</h1>
          <p className={styles.lead}>
            Plan departures, route through every confirmed stop, and let passengers follow the bus on a page that tells
            the truth about when it will arrive.
          </p>
          <div className={styles.ctas}>
            <Link href="/login" className={styles.primary}>
              Sign in to the dashboard <ArrowRight size={18} aria-hidden />
            </Link>
            <a href="#how" className={styles.secondary}>
              How it works
            </a>
          </div>
        </section>

        <section id="how" className={styles.features} aria-label="What RouteSync does">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <article key={title} className={styles.feature}>
              <span className={styles.icon}>
                <Icon size={22} aria-hidden />
              </span>
              <h2>{title}</h2>
              <p>{text}</p>
            </article>
          ))}
        </section>
      </main>

      <footer className={styles.footer}>
        <span>
          Map data © OpenStreetMap contributors. Tiles © MapTiler. Routing by openrouteservice.
        </span>
        <ApiStatus />
      </footer>
    </div>
  );
}
