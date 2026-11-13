# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Backend exists: Python 3.12, FastAPI (JSON API + a throwaway Jinja test page), arq workers,
Postgres (PostGIS + pgvector), Redis, S3-compatible storage, LiteLLM (local Ollama).

Frontend, delegated: **Next.js (App Router) + TypeScript**, a separate web app that talks to the
FastAPI JSON API; styling through design tokens as CSS custom properties (Tailwind allowed on top
of them). Chosen because the system design already plans a Next.js client, the assistant needs
streamed (SSE) responses, and the same app must later serve outside paying users. The Jinja page
at `src/housing_netherlands/api/templates/index.html` is a step-1 test harness, not a design
reference.

## Users

A couple in Rotterdam looking for a rental home together. Neither reads Dutch comfortably: the
interface is English, and Dutch listing text has to be summarised, translated and explained.
They care about what they can afford on their incomes, the commute to both of their jobs, and
must-haves. Both partners use it, and one of them weighs how attractive it is heavily: the app has
to be a pleasure to browse, with listings that look inviting, not just a data tool. In the Rotterdam market good flats go within hours, so the job is to spot a fitting
listing quickly, trust the judgement, and contact the landlord before others do.

Later (roadmap step 8) outside paying users may sign up; they are not designed for yet.

## Product Purpose

A personal housing dashboard for the Dutch rental market. It collects listings, enriches them
with Dutch open data and AI, and ranks them for one household's profile. Success for the
personal phase: "we use it for our own house hunt instead of the source sites."

## Positioning

Listings are not the product; enrichment and matching are. Existing alert services sort by
date; this ranks by fit to the household: income-based affordability, commute times to both
jobs, must-haves, plus neighbourhood profiles from open data (BAG, CBS, Leefbaarometer),
building facts, AI summaries/translation, red-flag extraction and a rent-fairness estimate
under the Dutch points system (woningwaarderingsstelsel). An assistant answers questions like
"what can we afford near both our jobs?" from real data via tools, not model memory.

## Operating Context

- Listings come from Dutch rental sites (huurwoningen.nl implemented; pararius, funda, huurstunt,
  DirectWonen, Kamernet and others planned), pasted links, and later alert emails.
- Today: paste a huurwoningen.nl URL, a background job imports it; summaries take about a minute
  on CPU. Every heavy step is asynchronous, so the UI must show job state (queued, running,
  succeeded, failed with a reason) rather than block.
- Alerts (planned step 5) go out by email or Telegram when a listing's score passes a threshold,
  with a score breakdown; the web app is where the couple follows up.
- Contacting landlords and agencies happens outside the product (site forms, email).

## Capabilities and Constraints

Built (step 1): import a listing by URL, archive the raw page, parse to a normalised `Listing`
(title, price €/month, m², rooms, bedrooms, address, postcode, city, coordinates, description),
English AI summary with exactly three key facts, job status API, listing list API.

Roadmap, not built: open-data enrichment and BAG address matching (2), scheduled ingestion and
cross-site dedupe (3), structured AI enrichment, red flags, rent-points estimate (4), user
profile with salary, work locations and must-haves, scoring, commute, alerts (5), web app with
feed, listing detail, saved/compare, neighbourhood pages and assistant (6), VPS deploy (7),
SaaS: auth, quotas, billing, licensed sources (8). Buying is a later feature, not in scope.

Constraints:
- Any field can be missing: price, area, rooms, summary. The UI shows "unknown"/pending honestly,
  never a guess.
- Scraped sources are for personal use only and never reach a paying user.
- Salary and work locations are personal data: encrypted at rest, deletable, never sent to an
  LLM with a name attached.
- LLM is local Ollama; summaries can be slow or fail and retry.

Terminology: listing (one ad on one source), property (one real home across sites), import job,
summary / key facts, fit score, enrichment.

Undecided: fit-score formula and thresholds, commute engine output format (self-hosted
OpenTripPlanner planned), alert channels' exact behaviour, product name beyond the working name.

## Brand Commitments

Working name "NL Housing". No logo, voice guide or brand assets yet. The earlier handoff in
`docs/home-design-v1/` (tokens, Inter, card layout) is explicitly discarded as visual authority.

## Evidence on Hand

- Product brief and roadmap: `docs/NL Housing App.pdf`; architecture: `docs/NL Housing App — System Design.pdf`.
- Real listing data: whatever has been imported into the local database; three real Rotterdam
  listings are described in `docs/home-design-v1/DESIGN.md` (Zuidplein €915, Groenendaal €1,207,
  Hanoistraat €1,432). The fit and commute values there are placeholders.
- Fixture page: `tests/fixtures/huurwoningen/detail.html`.
- Listing photos: the source library (`pyhuurwoningen`) parses each listing's main photo
  (`image_url`), but the `Listing` model does not store it yet.
- None yet: fit scores, commute times, neighbourhood stats, red flags, rent-fairness figures,
  user profile data. Do not fabricate these as if real; mark sample
  values as placeholders.

## Product Principles

1. Fit before freshness: rank and explain by how well a home suits this household, and show why
   (score breakdown), never an opaque number.
2. Explain the Dutch: every listing should be understandable without reading Dutch; translate,
   summarise and flag what a newcomer would miss.
3. Honest about the data: show unknowns, pending jobs and failures plainly; answers come from
   data, not guesses.
4. Speed to act: the path from "new listing" to "we want this, contact them" is short.
5. Built for two, ready for more: shared household decisions now, without choices that block
   multi-user later.

## Accessibility & Inclusion

English UI for non-Dutch speakers; Dutch terms (e.g. servicekosten, huurtoeslag, points system)
explained in plain English where they appear. No specific standard set beyond sensible WCAG AA.
