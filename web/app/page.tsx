import { House, PlugZap, SearchX } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { AppHeader } from "@/components/AppHeader";
import { ListingCard } from "@/components/ListingCard";
import { SearchBar } from "@/components/SearchBar";
import { ApiError, api, type ListingView } from "@/lib/api";
import { hasFilters, parseFilters, type Filters } from "@/lib/filters";
import styles from "./page.module.css";

export const dynamic = "force-dynamic";

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function FeedPage({ searchParams }: Props) {
  const filters = parseFilters(await searchParams);
  const [result, places] = await Promise.all([load(filters), api.listPlaces().catch(() => [])]);
  const filtered = hasFilters(filters);

  return (
    <>
      <AppHeader>
        <SearchBar filters={filters} places={places} />
      </AppHeader>
      <main className={styles.main}>
        <section className={styles.feed} aria-labelledby="feed-title" aria-live="polite">
          <div className={styles.head}>
            <h1 id="feed-title" className={styles.title}>
              Homes for you two
            </h1>
            {"listings" in result && result.listings.length > 0 && (
              <p className={styles.count}>{countText(result.listings.length, filtered)}</p>
            )}
          </div>
          {"message" in result ? (
            <Notice icon={<PlugZap size={28} />} title="We couldn't load your homes">
              {result.message}
            </Notice>
          ) : result.listings.length > 0 ? (
            <ul className={styles.grid}>
              {result.listings.map((view) => (
                <li key={view.id}>
                  <ListingCard view={view} />
                </li>
              ))}
            </ul>
          ) : filtered ? (
            <Notice icon={<SearchX size={28} />} title="No homes match these filters">
              We only have a handful of listings until automatic collection of Rotterdam rentals
              is switched on. Try fewer filters, or{" "}
              <Link href="/" className={styles.link}>
                clear them all
              </Link>
              .
            </Notice>
          ) : (
            <Notice icon={<House size={28} />} title="No homes yet">
              Listings appear here once automatic collection of Rotterdam rentals is switched on.
            </Notice>
          )}
        </section>
      </main>
    </>
  );
}

async function load(filters: Filters): Promise<{ listings: ListingView[] } | { message: string }> {
  try {
    return { listings: await api.listListings(filters) };
  } catch (error) {
    if (error instanceof ApiError) return { message: error.message };
    throw error;
  }
}

function countText(n: number, filtered: boolean): string {
  if (n === 1) return filtered ? "1 home matches" : "1 home so far";
  return filtered ? `${n} homes match` : `${n} homes so far`;
}

function Notice({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className={styles.notice}>
      <span className={styles.noticeIcon} aria-hidden="true">
        {icon}
      </span>
      <h2 className={styles.noticeTitle}>{title}</h2>
      <p className={styles.noticeText}>{children}</p>
    </div>
  );
}
