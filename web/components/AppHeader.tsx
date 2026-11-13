import { House } from "lucide-react";
import Link from "next/link";
import { ImportBox } from "./ImportBox";
import styles from "./AppHeader.module.css";

/**
 * The floating bar: brand plus the paste-a-link import, always within reach.
 * Pinned to the top on wider screens, to the bottom (thumb zone) on phones.
 */
export function AppHeader() {
  return (
    <header className={styles.bar}>
      <Link href="/" className={styles.brand} aria-label="NL Housing, home">
        <span className={styles.mark} aria-hidden="true">
          <House size={18} strokeWidth={2.4} />
        </span>
        <span className={styles.name}>NL Housing</span>
      </Link>
      <ImportBox />
    </header>
  );
}
