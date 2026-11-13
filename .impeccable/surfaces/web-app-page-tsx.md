---
version: 1
slug: "web-app-page-tsx"
primary_target: "web/app/page.tsx"
related_targets: []
---

# Feed (home)

Mode: Operate. Target: `web/app/page.tsx` (Next.js App Router), data from the FastAPI JSON API.

## Scope
- The couple's home screen: paste a listing link to import it, follow the import job, browse imported listings, open one.
- Real data only (title, rent, m², rooms, bedrooms, postcode, neighbourhood, city, photo, English summary + key facts). Fit, commute and flags do not exist yet; the card leaves a place for them but shows nothing invented.
- Phone and desktop equally. Detail page is the next ticket; until it exists a card opens the source listing in a new tab.
- Out of scope: saved, neighbourhoods, profile, assistant (nav shows only what works).

## States
Empty feed (first run: invite a paste), import queued/running (about a minute), import failed with reason, listing without photo, without price/area/summary, summary pending, API unreachable.

## Direction contract
THESIS: A house hunt should feel like browsing homes you'd love, not reading a database. Refuses the property-portal results grid with filters on top and photo-left rows.
OWN-WORLD: Warm tinted ground, white soft-cornered cards (24px outer, 16px photo), one saturated tomato action colour used only on things you can press, rounded humanist sans (Nunito) at comfortable sizes, plain-language labels written like a person ("Have a look", "We're reading it now").
STORY: Paste a link you found, see it being read, then a feed of photo-led cards; each says in one English line what the place is, with rent and size; tap to look closer.
FIRST VIEWPORT: Top bar: name left, nav (Feed) and on phone a thumb-reachable bottom bar. Below: a wide rounded paste box with the only coloured button ("Add it"); status line under it while importing. Then heading "Homes for you two" with count, and a responsive grid of photo cards (3 columns desktop, 1 phone).
FORM: challenger digital-design-canon-warm-consumer-app-surface (catalog, chosen over the assigned direction in round 3), seed:74d7437ee3da2b84
SIGNATURE: the action colour appears only where something can be done; press gives a soft spring. Each card carries its summary's first sentence as a one-line character note.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
