"use client";

import { ChevronDown, MapPin, Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTransition, type FormEvent, type ReactNode } from "react";
import { CHOICES, INTERIORS, hasFilters, parseFilters, toQuery, type Filters } from "@/lib/filters";
import { formatRent } from "@/lib/format";
import styles from "./SearchBar.module.css";

/**
 * Location search plus filter chips. The URL holds the filters (shareable, back button works);
 * chips apply as soon as they change, the place applies on Search / Enter.
 */
export function SearchBar({ filters, places }: { filters: Filters; places: string[] }) {
  const router = useRouter();
  const [searching, startSearch] = useTransition();

  const apply = (form: HTMLFormElement) => {
    const params = Object.fromEntries(new FormData(form)) as Record<string, string>;
    const query = toQuery(parseFilters(params));
    startSearch(() => router.push(query ? `/?${query}` : "/"));
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    apply(event.currentTarget);
  };

  return (
    // Keyed by the filters so the fields reset on back/forward navigation.
    <form key={toQuery(filters)} className={styles.bar} onSubmit={onSubmit} role="search">
      <div className={styles.searchRow}>
        <label className={styles.field}>
          <MapPin size={18} aria-hidden="true" className={styles.fieldIcon} />
          <span className="visually-hidden">Place</span>
          <input
            name="place"
            type="search"
            list="places"
            defaultValue={filters.place}
            placeholder="Area, city or postcode"
            autoComplete="off"
            maxLength={100}
            className={styles.input}
          />
          <datalist id="places">
            {places.map((place) => (
              <option key={place} value={place} />
            ))}
          </datalist>
        </label>
        <button type="submit" className={styles.searchButton} disabled={searching}>
          <Search size={18} aria-hidden="true" />
          <span className={styles.searchLabel}>{searching ? "Searching…" : "Search"}</span>
        </button>
      </div>

      <div className={styles.chips} onChange={(e) => apply(e.currentTarget.closest("form")!)}>
        <Choice name="max_rent" label="Max rent" value={filters.max_rent} any="Any rent">
          {CHOICES.max_rent.map((n) => (
            <option key={n} value={n}>
              Up to {formatRent(n)}
            </option>
          ))}
        </Choice>
        <Choice name="min_rooms" label="Rooms" value={filters.min_rooms} any="Any rooms">
          {CHOICES.min_rooms.map((n) => (
            <option key={n} value={n}>
              {n}+ rooms
            </option>
          ))}
        </Choice>
        <Choice name="min_area" label="Size" value={filters.min_area} any="Any size">
          {CHOICES.min_area.map((n) => (
            <option key={n} value={n}>
              {n}+ m²
            </option>
          ))}
        </Choice>
        <Choice name="interior" label="Interior" value={filters.interior} any="Any interior">
          {Object.entries(INTERIORS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Choice>
        <label className={`${styles.chip} ${filters.new_build ? styles.active : ""}`}>
          <input
            type="checkbox"
            name="new_build"
            value="true"
            defaultChecked={filters.new_build}
            className={styles.check}
          />
          New build
        </label>
        {hasFilters(filters) && (
          <button type="button" className={styles.clear} onClick={() => router.push("/")}>
            <X size={16} aria-hidden="true" />
            Clear
          </button>
        )}
      </div>
    </form>
  );
}

function Choice(props: {
  name: string;
  label: string;
  any: string;
  value: string | number | undefined;
  children: ReactNode;
}) {
  const active = props.value !== undefined;
  return (
    <label className={`${styles.chip} ${styles.select} ${active ? styles.active : ""}`}>
      <span className="visually-hidden">{props.label}</span>
      <select name={props.name} defaultValue={props.value ?? ""}>
        <option value="">{props.any}</option>
        {props.children}
      </select>
      <ChevronDown size={16} aria-hidden="true" className={styles.chevron} />
    </label>
  );
}
