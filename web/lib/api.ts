/**
 * Typed client for the FastAPI backend. Server-only: the browser talks to Next server actions,
 * which call this, so the API needs no CORS and its URL stays configuration.
 */
import "server-only";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export interface Job {
  job_id: string;
  status: JobStatus;
  error: string | null;
}

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      cache: "no-store",
      headers: { "content-type": "application/json", ...init?.headers },
    });
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
  listListings: (limit = 50) => request<ListingView[]>(`/api/listings?limit=${limit}`),
  getJob: (jobId: string) => request<Job>(`/api/jobs/${encodeURIComponent(jobId)}`),
  importListing: (url: string) =>
    request<{ job_id: string }>("/api/listings/import", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
};
