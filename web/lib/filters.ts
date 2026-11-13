/**
 * Search filters: one definition shared by the URL (source of truth), the search bar and the
 * API client. Choices live here so changing them is configuration, not component edits.
 */

export const INTERIORS = {
  bare: "Unfurnished (kaal)",
  upholstered: "Semi-furnished (gestoffeerd)",
  furnished: "Furnished",
} as const;

export type Interior = keyof typeof INTERIORS;

export const CHOICES = {
  max_rent: [1000, 1250, 1500, 1750, 2000, 2500],
  min_rooms: [1, 2, 3, 4],
  min_area: [40, 60, 80, 100],
} as const;

export interface Filters {
  place?: string;
  max_rent?: number;
  min_rooms?: number;
  min_area?: number;
  new_build?: boolean;
  interior?: Interior;
}

type Params = Record<string, string | string[] | undefined>;

const MAX_PLACE_LENGTH = 100;

function single(value: string | string[] | undefined): string | undefined {
  const text = (Array.isArray(value) ? value[0] : value)?.trim();
  return text || undefined;
}

function count(value: string | string[] | undefined): number | undefined {
  const n = Number(single(value));
  return Number.isInteger(n) && n > 0 ? n : undefined;
}

/** Read filters from URL params, silently dropping anything malformed. */
export function parseFilters(params: Params): Filters {
  const place = single(params.place)?.slice(0, MAX_PLACE_LENGTH);
  const interior = single(params.interior);
  const filters: Filters = {
    place,
    max_rent: count(params.max_rent),
    min_rooms: count(params.min_rooms),
    min_area: count(params.min_area),
    new_build: single(params.new_build) === "true" || undefined,
    interior: interior && interior in INTERIORS ? (interior as Interior) : undefined,
  };
  return Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== undefined));
}

export function toQuery(filters: Filters): string {
  const entries = Object.entries(filters).map(([key, value]) => [key, String(value)]);
  return new URLSearchParams(entries).toString();
}

export const hasFilters = (filters: Filters) => Object.keys(filters).length > 0;

/** `filters` with one field changed; an empty value removes it. Validated like the URL. */
export function withFilter(filters: Filters, name: keyof Filters, value: string): Filters {
  const params = Object.fromEntries(new URLSearchParams(toQuery(filters)));
  return parseFilters({ ...params, [name]: value });
}

/** The preset choices plus the current value, so a shared off-list value (1100) still shows. */
export function choicesWith(choices: readonly number[], current: number | undefined): number[] {
  const all = current === undefined ? [...choices] : [...new Set([...choices, current])];
  return all.sort((a, b) => a - b);
}
