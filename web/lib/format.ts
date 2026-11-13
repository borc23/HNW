import type { Listing } from "@/lib/api";

const euros = new Intl.NumberFormat("en-NL", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
});

export const formatRent = (eur: number | null) => (eur === null ? null : euros.format(eur));

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** "59 m² · 4 rooms · 2 bedrooms", skipping whatever the listing doesn't say. */
export function formatFacts({ area_m2, rooms, bedrooms }: Listing): string {
  return [
    area_m2 !== null && `${Math.round(area_m2)} m²`,
    rooms !== null && plural(rooms, "room"),
    bedrooms !== null && plural(bedrooms, "bedroom"),
  ]
    .filter(Boolean)
    .join(" · ");
}

export const formatPlace = ({ neighbourhood, city }: Listing) =>
  [neighbourhood, city].filter(Boolean).join(", ");

/** Dutch dwelling types that open source titles, in plain English. */
const DWELLING_TYPES: Record<string, string> = {
  appartement: "Apartment",
  bovenwoning: "Upstairs flat",
  benedenwoning: "Ground-floor flat",
  eengezinswoning: "Family house",
  huis: "House",
  kamer: "Room",
  maisonnette: "Maisonette",
  penthouse: "Penthouse",
  studio: "Studio",
  woning: "Home",
};

/** "Appartement Peitkreek in Rotterdam" becomes "Apartment Peitkreek"; the city shows separately. */
export function englishTitle({ title, city }: Listing): string {
  const suffix = city ? ` in ${city}` : "";
  const name = suffix && title.endsWith(suffix) ? title.slice(0, -suffix.length) : title;
  const [first, ...rest] = name.split(" ");
  const type = DWELLING_TYPES[first.toLowerCase()];
  return type && rest.length ? `${type} ${rest.join(" ")}` : name;
}

/** The summary's first sentence: one line that says what the place is. */
export function firstSentence(text: string): string {
  const match = text.match(/^.+?[.!?](?=\s|$)/);
  return (match ? match[0] : text).trim();
}
