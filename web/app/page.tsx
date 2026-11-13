import { House, PlugZap } from "lucide-react";
import type { ReactNode } from "react";
import { ListingCard } from "@/components/ListingCard";
import { ApiError, api, type ListingView } from "@/lib/api";
import styles from "./page.module.css";

export const dynamic = "force-dynamic";

export default async function FeedPage() {
  const result = await loadListings();

  return (
    <main className={styles.main}>
      <section className={styles.feed} aria-labelledby="feed-title">
        <div className={styles.head}>
          <h1 id="feed-title" className={styles.title}>
            Homes for you two
          </h1>
          {"listings" in result && result.listings.length > 0 && (
            <p className={styles.count}>{placesText(result.listings.length)}</p>
          )}
        </div>
        {"message" in result ? (
          <Notice icon={<PlugZap size={28} />} title="We couldn't load your homes">
            {result.message}
          </Notice>
        ) : result.listings.length === 0 ? (
          <Notice icon={<House size={28} />} title="Nothing here yet">
            Paste a link from huurwoningen.nl above and we'll read it for you.
          </Notice>
        ) : (
          <ul className={styles.grid}>
            {result.listings.map((view) => (
              <li key={view.id}>
                <ListingCard view={view} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}

async function loadListings(): Promise<{ listings: ListingView[] } | { message: string }> {
  try {
    return { listings: await api.listListings() };
  } catch (error) {
    if (error instanceof ApiError) return { message: error.message };
    throw error;
  }
}

const placesText = (n: number) => (n === 1 ? "1 place so far" : `${n} places so far`);

function Notice({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className={styles.notice}>
      <span className={styles.noticeIcon} aria-hidden="true">
        {icon}
      </span>
      <h2 className={styles.noticeTitle}>{title}</h2>
      <p>{children}</p>
    </div>
  );
}
