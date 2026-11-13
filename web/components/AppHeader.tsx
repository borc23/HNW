import { House } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import styles from "./AppHeader.module.css";

/**
 * The floating bar: brand plus the page's tools (search and filters), always within reach.
 * Pinned to the top on wider screens, to the bottom (thumb zone) on phones.
 */
export function AppHeader({ children }: { children: ReactNode }) {
  return (
    <header className={styles.bar}>
      <Link href="/" className={styles.brand} aria-label="NL Housing, home">
        <span className={styles.mark} aria-hidden="true">
          <House size={18} strokeWidth={2.4} />
        </span>
        <span className={styles.name}>NL Housing</span>
      </Link>
      {children}
    </header>
  );
}
