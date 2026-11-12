import { ApiStatus } from "@/components/ApiStatus";

import styles from "./page.module.css";

export default function Home() {
  return (
    <main className={styles.main}>
      <h1 className={styles.title}>RouteSync</h1>
      <p className={styles.tagline}>Intelligence behind every journey.</p>
      <ApiStatus />
    </main>
  );
}
