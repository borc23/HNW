"use client";

import { ChevronDown, MapPin, Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useOptimistic, useState, useTransition, type FormEvent, type ReactNode } from "react";
import {
  CHOICES,
  INTERIORS,
  choicesWith,
  hasFilters,
  toQuery,
  withFilter,
  type Filters,
} from "@/lib/filters";
import { formatRent } from "@/lib/format";
import styles from "./SearchBar.module.css";

/**
 * Location search plus filter chips. The URL holds the applied filters (shareable, back button
 * works). A chip changes only its own filter, immediately; the place applies on Search / Enter.
 */
export function SearchBar({ filters, places }: { filters: Filters; places: string[] }) {
  const router = useRouter();
  const [searching, startSearch] = useTransition();
  // Chips show the new value straight away, before the page has re-rendered.
  const [shown, setShown] = useOptimistic(filters);
  const place = usePlaceDraft(filters.place);

  const go = (next: Filters) =>
    startSearch(() => {
      setShown(next);
      const query = toQuery(next);
      router.push(query ? `/?${query}` : "/");
    });

  const set = (name: keyof Filters, value: string) => go(withFilter(shown, name, value));

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    set("place", place.value);
  };

  return (
    <form className={styles.bar} onSubmit={onSubmit} role="search">
      <div className={styles.searchRow}>
        <label className={styles.field}>
          <MapPin size={18} aria-hidden="true" className={styles.fieldIcon} />
          <span className="visually-hidden">Place</span>
          <input
            type="search"
            list="places"
            value={place.value}
            onChange={(e) => place.set(e.target.value)}
            placeholder="Area, city or postcode"
            autoComplete="off"
            maxLength={100}
            className={styles.input}
          />
          <datalist id="places">
            {places.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </label>
        <button type="submit" className={styles.searchButton} disabled={searching}>
          <Search size={18} aria-hidden="true" />
          <span className={styles.searchLabel}>{searching ? "Searching…" : "Search"}</span>
        </button>
      </div>

      <div className={styles.chips}>
        <Choice
          label="Max rent"
          any="Any rent"
          value={shown.max_rent}
          onChange={(v) => set("max_rent", v)}
        >
          {choicesWith(CHOICES.max_rent, shown.max_rent).map((n) => (
            <option key={n} value={n}>
              Up to {formatRent(n)}
            </option>
          ))}
        </Choice>
        <Choice
          label="Rooms"
          any="Any rooms"
          value={shown.min_rooms}
          onChange={(v) => set("min_rooms", v)}
        >
          {choicesWith(CHOICES.min_rooms, shown.min_rooms).map((n) => (
            <option key={n} value={n}>
              {n}+ rooms
            </option>
          ))}
        </Choice>
        <Choice label="Size" any="Any size" value={shown.min_area} onChange={(v) => set("min_area", v)}>
          {choicesWith(CHOICES.min_area, shown.min_area).map((n) => (
            <option key={n} value={n}>
              {n}+ m²
            </option>
          ))}
        </Choice>
        <Choice
          label="Interior"
          any="Any interior"
          value={shown.interior}
          onChange={(v) => set("interior", v)}
        >
          {Object.entries(INTERIORS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Choice>
        <label className={`${styles.chip} ${shown.new_build ? styles.active : ""}`}>
          <input
            type="checkbox"
            checked={!!shown.new_build}
            onChange={(e) => set("new_build", e.target.checked ? "true" : "")}
            className={styles.check}
          />
          New build
        </label>
        {hasFilters(shown) && (
          <button type="button" className={styles.clear} onClick={() => go({})}>
            <X size={16} aria-hidden="true" />
            Clear
          </button>
        )}
      </div>
    </form>
  );
}

/**
 * The place being typed. It is a draft until submitted, so chips never send half-typed text;
 * it re-syncs only when the applied place changes (back/forward, Clear).
 */
function usePlaceDraft(applied: string | undefined) {
  const [value, set] = useState(applied ?? "");
  const [synced, setSynced] = useState(applied);
  if (applied !== synced) {
    setSynced(applied);
    set(applied ?? "");
  }
  return { value, set };
}

function Choice(props: {
  label: string;
  any: string;
  value: string | number | undefined;
  onChange: (value: string) => void;
  children: ReactNode;
}) {
  const active = props.value !== undefined;
  return (
    <label className={`${styles.chip} ${styles.select} ${active ? styles.active : ""}`}>
      <span className="visually-hidden">{props.label}</span>
      <select value={props.value ?? ""} onChange={(e) => props.onChange(e.target.value)}>
        <option value="">{props.any}</option>
        {props.children}
      </select>
      <ChevronDown size={16} aria-hidden="true" className={styles.chevron} />
    </label>
  );
}
