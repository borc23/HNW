import { ArrowUpRight, ImageOff, MapPin } from "lucide-react";
import type { ListingView } from "@/lib/api";
import {
  englishTitle,
  firstSentence,
  formatDetails,
  formatFacts,
  formatPlace,
  formatRent,
} from "@/lib/format";
import styles from "./ListingCard.module.css";

/** One home in the feed. Until the detail page exists, it opens the source listing. */
export function ListingCard({ view }: { view: ListingView }) {
  const { listing, summary } = view;
  const rent = formatRent(listing.price_eur);
  const facts = formatFacts(listing);
  const details = formatDetails(listing);
  const place = formatPlace(listing);

  return (
    <article className={styles.card}>
      <a href={listing.url} target="_blank" rel="noreferrer" className={styles.link}>
        <div className={styles.photo}>
          {listing.new_build && <span className={styles.tag}>New build</span>}
          {listing.image_url ? (
            // Hotlinked source photo; next/image would need every source host configured.
            <img src={listing.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" />
          ) : (
            <span className={styles.noPhoto}>
              <ImageOff size={22} aria-hidden="true" />
              No photo yet
            </span>
          )}
        </div>
        <div className={styles.body}>
          <h2 className={styles.title}>{englishTitle(listing)}</h2>
          {place && (
            <p className={styles.place}>
              <MapPin size={15} aria-hidden="true" />
              {place}
            </p>
          )}
          <p className={summary ? styles.note : styles.pending}>
            {summary ? firstSentence(summary.summary_en) : "English summary on its way."}
          </p>
          {facts && <p className={styles.facts}>{facts}</p>}
          {details && <p className={styles.details}>{details}</p>}
          <div className={styles.footer}>
            <p className={styles.rent}>
              {rent ? (
                <>
                  {rent}
                  <span> / month</span>
                </>
              ) : (
                <span>Rent not listed</span>
              )}
            </p>
            <span className={styles.cta}>
              Have a look
              <ArrowUpRight size={16} aria-hidden="true" />
              <span className="visually-hidden"> (opens the original listing)</span>
            </span>
          </div>
        </div>
      </a>
    </article>
  );
}
