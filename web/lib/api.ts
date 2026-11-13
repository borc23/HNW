/**
 * Typed client for the FastAPI backend. Server-only: pages render on the Next server, so the
 * API needs no CORS and its URL stays configuration.
 */
import "server-only";
import { toQuery, type Filters, type Interior } from "@/lib/filters";

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const PLACES_REVALIDATE_S = 300; // suggestions change slowly; don't query them on every render

export interface Listing {
  url: string;
  title: string;
  price_eur: number | null;
  area_m2: number | null;
  rooms: number | null;
  bedrooms: number | null;
  postcode: string | null;
  city: string | null;
  neighbourhood: string | null;
  image_url: string | null;
  build_year: number | null;
  new_build: boolean | null;
  interior: Interior | null;
}

export interface ListingView {
  id: number;
  listing: Listing;
  summary: { summary_en: string; key_facts: string[] } | null;
}

/** An API call that failed; `message` is safe to show to the user. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

/** `revalidateS` caches the response that many seconds; without it, every call is fresh. */
async function request<T>(path: string, revalidateS?: number): Promise<T> {
  const caching: RequestInit =
    revalidateS === undefined ? { cache: "no-store" } : { next: { revalidate: revalidateS } };
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, caching);
  } catch {
    throw new ApiError("We can't reach the NL Housing server right now. Is it running?");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(errorMessage(body) ?? `Server error (${response.status}).`, response.status);
  }
  return body as T;
}

function errorMessage(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "error" in detail) return String(detail.error);
  return null;
}

export const api = {
  listListings: (filters: Filters = {}, limit = 50) => {
    const query = toQuery(filters);
    return request<ListingView[]>(`/api/listings?limit=${limit}${query && `&${query}`}`);
  },
  listPlaces: () => request<string[]>("/api/places", PLACES_REVALIDATE_S),
};
