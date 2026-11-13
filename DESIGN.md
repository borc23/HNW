---
name: NL Housing
description: Rotterdam rentals, read and explained in English, browsed like homes you'd love.
colors:
  action: "#d4401c"
  action-hover: "#b8350f"
  action-ink: "#ffffff"
  ground: "#f6efe8"
  surface: "#ffffff"
  surface-sunk: "#f1e7dd"
  ink: "#2a2420"
  ink-muted: "#6b5f57"
  line: "#e8dccf"
  ok: "#24693f"
  ok-tint: "#e3f1e6"
  problem: "#a8261b"
  problem-tint: "#fbe6e2"
typography:
  headline:
    fontFamily: "Nunito, ui-rounded, system-ui, sans-serif"
    fontSize: "clamp(1.75rem, 1.4rem + 1.2vw, 2.25rem)"
    fontWeight: 800
    lineHeight: 1.15
    letterSpacing: "-0.01em"
  price:
    fontFamily: "Nunito, ui-rounded, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 800
    fontFeature: "tnum"
  title:
    fontFamily: "Nunito, ui-rounded, system-ui, sans-serif"
    fontSize: "1.1875rem"
    fontWeight: 800
    lineHeight: 1.25
  body:
    fontFamily: "Nunito, ui-rounded, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "tnum"
  label:
    fontFamily: "Nunito, ui-rounded, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 700
rounded:
  sm: "12px"
  inner: "16px"
  card: "24px"
spacing:
  gutter: "clamp(16px, 4vw, 40px)"
  content: "1160px"
  card-inset: "10px"
  panel: "clamp(16px, 3vw, 24px)"
  grid-gap: "20px"
components:
  button-primary:
    backgroundColor: "{colors.action}"
    textColor: "{colors.action-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.inner}"
    padding: "0 24px"
    height: "52px"
  button-primary-hover:
    backgroundColor: "{colors.action-hover}"
  button-primary-disabled:
    backgroundColor: "{colors.line}"
    textColor: "{colors.ink-muted}"
  button-card-cta:
    backgroundColor: "{colors.action}"
    textColor: "{colors.action-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "40px"
  input-paste:
    backgroundColor: "{colors.surface-sunk}"
    textColor: "{colors.ink}"
    rounded: "{rounded.inner}"
    padding: "0 18px"
    height: "52px"
  input-paste-focus:
    backgroundColor: "{colors.surface}"
  card-listing:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "{spacing.card-inset}"
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.card}"
    padding: "{spacing.panel}"
  status-working:
    backgroundColor: "{colors.surface-sunk}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "10px 14px"
  status-ok:
    backgroundColor: "{colors.ok-tint}"
    textColor: "{colors.ok}"
    rounded: "{rounded.sm}"
    padding: "10px 14px"
  status-problem:
    backgroundColor: "{colors.problem-tint}"
    textColor: "{colors.problem}"
    rounded: "{rounded.sm}"
    padding: "10px 14px"
---

# Design System: NL Housing

## Overview

**Creative North Star: "Homes You'd Love"**

A warm consumer app, not a property portal. The screen is a warm tinted ground with soft white cards floating on it; each card is photo-led and speaks in one plain English sentence before it gives you numbers. Density is relaxed: one paste panel, then a grid of generous cards, with nothing above them that looks like a filter bar or a results table.

Colour does one job. A single saturated tomato appears only on things you can press, so a glance at the page tells you exactly what can be done. Everything else is warm neutrals: cream ground, white surfaces, a sunken oat tone for wells and placeholders, and a dark brown-black ink. Type is Nunito throughout, a rounded humanist sans used heavy (800) for anything that names a thing and regular for reading.

Motion is reserved for touch. Pressing a card or the main button gives a small spring scale; nothing bounces in on load, nothing animates for decoration. Copy is written like a person talking to a couple ("Found a place you like?", "We're reading it now", "Have a look").

**Key Characteristics:**
- Warm cream ground with white, softly shadowed cards.
- One action colour (tomato), only on pressable things.
- Two nested radii: 24px outside, 16px inside.
- Nunito at 800 for names and prices, 400 for reading.
- Soft spring on press only.
- Plain-language, second-person copy.

## Colors

A warm, low-contrast neutral world with exactly one loud colour and two quiet status pairs.

### Primary
- **Tomato** (`action`): the fill of every pressable control: the "Add it" button, the "Have a look" pill on each card, the focus ring, the focused input border, the text caret. Never used for decoration, headings, icons at rest, or status.
- **Deep Tomato** (`action-hover`): hover state of tomato controls only.
- **Tomato Ink** (`action-ink`): white text on tomato.

### Neutral
- **Warm Cream** (`ground`): the page background behind everything.
- **Card White** (`surface`): cards, the paste panel, empty/error notices, and the focused input.
- **Oat Well** (`surface-sunk`): sunken surfaces: the idle input, photo placeholders, the "working" status line, notice icon tiles.
- **Espresso Ink** (`ink`): all primary text and the brand mark tile.
- **Walnut Muted** (`ink-muted`): secondary text: place line, hints, counts, "/ month", pending notes, placeholder text.
- **Linen Line** (`line`): the disabled button fill and the scrollbar thumb; the system draws no visible hairlines on cards.

### Status
- **Leaf** (`ok`) on **Mint Tint** (`ok-tint`): the import-succeeded line.
- **Brick** (`problem`) on **Blush Tint** (`problem-tint`): import failures and errors. Deliberately darker and redder than tomato so an error never reads as a button.

### Named Rules
**The Pressable-Only Rule.** Tomato marks what can be pressed and nothing else. When a control stops being pressable (disabled, busy) it loses tomato entirely and falls back to Linen Line with muted ink.

**The Tinted-Status Rule.** Status is shown as a tinted strip with dark text of the same hue, never as a saturated filled block that could compete with the action colour.

## Typography

**Display Font:** Nunito (with ui-rounded, system-ui, sans-serif)
**Body Font:** Nunito (same family)

**Character:** One rounded humanist family carries the whole voice; hierarchy comes from weight (800 vs 400/600) and size, not from a second face. Numerals are tabular everywhere so rents and areas line up.

### Hierarchy
- **Headline** (800, clamp 1.75rem to 2.25rem, 1.15, -0.01em): the one section heading per page ("Homes for you two"). Balanced wrapping.
- **Price** (800, 1.5rem): the rent on each card; its "/ month" suffix drops to label size, 600, muted.
- **Title** (800, 1.1875rem, 1.25): card titles, the paste-panel prompt, notice titles, the brand name.
- **Body** (400, 1rem, 1.5): summary sentences and notice text.
- **Label** (600 to 800, 0.875rem): facts line (700), place line (600, muted), button and pill text (800), hints and status lines (600).

### Named Rules
**The Weight-Not-Face Rule.** Hierarchy is made with Nunito weight and size. Don't introduce a second family, uppercase tracking, or small-caps labels above headings.

## Layout

A single centered column capped at the content width (1160px) with a fluid side gutter (16px to 40px). The page stacks: brand row, the paste panel, then the feed heading row (heading left, count right on the same baseline, wrapping on narrow screens), then the card grid.

The grid is `auto-fill` with a 300px minimum track and 20px gaps, which lands at three columns on desktop and one column on phones without breakpoints. Cards stretch to the row height so footers (rent + pill) align across a row. The paste panel's input and button sit side by side and stack below 520px. Section spacing is generous (32px to 48px above the feed); internal spacing is small and soft (10px card inset, 14px above card body text, 10px between note and facts).

## Elevation & Depth

Depth comes from a soft, warm-tinted two-layer shadow on white cards over the cream ground; there are no borders around cards. Sunken wells (Oat Well) give the inverse cue for inputs and placeholders.

### Shadow Vocabulary
- **Card rest** (`0 1px 2px rgb(42 36 32 / 0.05), 0 10px 28px -12px rgb(42 36 32 / 0.16)`): every white container: listing cards, the paste panel, notices.
- **Card hover** (`0 1px 2px rgb(42 36 32 / 0.05), 0 18px 36px -14px rgb(42 36 32 / 0.24)`): listing cards on hover only; the card lifts by shadow, not by translation.

### Named Rules
**The Ink-Tinted Shadow Rule.** Shadows are tinted with the ink colour (42 36 32), never neutral black, and are always soft and diffuse.

## Shapes

Generous, friendly corners in a nested system: containers at 24px, things inside them at 16px (photos, the input, the main button), and small pressables and strips at 12px (card pill, status line, brand mark). The inner radius is always smaller than its container so the curves read concentric. Photos are cropped 4:3 inside the card with the 16px radius. Focus outlines are 3px tomato, offset 3px, with an 8px radius.

## Components

### Buttons
Tactile and sure of itself, and the only coloured things on the page.
- **Shape:** inner radius (16px) for the panel button; small radius (12px) for the in-card pill.
- **Primary ("Add it"):** tomato fill, white 800 text, 52px tall, 24px side padding; matches the input height so they read as one control.
- **Hover:** deep tomato, 160ms ease-out.
- **Active:** scales to 0.96 on the spring curve (280ms).
- **Disabled / busy:** Linen Line fill, muted ink text, no spring, label changes to "Adding…".
- **Card pill ("Have a look"):** 40px tall, 14px padding, label size 800 with a trailing arrow-up-right icon; darkens when the whole card link is hovered.

### Cards / Containers
- **Corner Style:** 24px outer, 16px photo.
- **Background:** Card White on Warm Cream.
- **Shadow Strategy:** Card rest, Card hover on listing cards (see Elevation).
- **Border:** none.
- **Internal Padding:** 10px inset around the photo; body 14px top, 8px sides.
- **Press:** the whole card scales to 0.98 on the spring curve (320ms).
- **Content order:** photo, title, place line with pin icon, one-sentence English note (or an italic muted "English summary on its way."), facts line, then footer with rent left and pill right.
- **Missing photo:** Oat Well block with an image-off icon and "No photo yet" in muted 700 label.

### Inputs / Fields
- **Style:** Oat Well fill, 2px transparent border, 16px radius, 52px tall, 18px side padding, muted placeholder.
- **Focus:** border turns tomato and the fill lifts to Card White (160ms ease-out); no glow.

### Status Line
A tinted strip under the paste input: 12px radius, 10px by 14px padding, label size 600, 18px leading icon. Working uses Oat Well with a spinning loader; done uses Leaf on Mint Tint; failure uses Brick on Blush Tint. At idle it collapses to a plain muted hint sentence.

### Notice (empty and error states)
A Card White panel, centered text, 48px vertical padding, with a 56px Oat Well icon tile (18px radius), a title-size 800 heading and a muted plain-language sentence.

### Navigation
Brand row only: a 34px Espresso Ink tile (12px radius) holding a house icon in cream, beside "NL Housing" at title size 800. No nav items ship until a second page exists.

## Do's and Don'ts

### Do:
- **Do** reserve tomato for controls a person can press, and remove it the moment a control can't be pressed.
- **Do** nest radii: 24px containers, 16px contents, 12px small pills and strips.
- **Do** put content on white cards with the ink-tinted soft shadow, on the warm cream ground, with no card borders.
- **Do** use the spring curve (`cubic-bezier(0.34, 1.4, 0.64, 1)`) only for press feedback (scale 0.96 to 0.98); use 160ms ease-out for colour changes.
- **Do** write labels and states as a person would say them ("Add it", "Have a look", "We're reading it now").
- **Do** use line icons inline at 15px to 28px beside text, never as decoration on their own.

### Don't:
- **Don't** use tomato for headings, icons at rest, status, links in prose, or decoration.
- **Don't** show an error in a colour that could be mistaken for the action colour; errors use Brick on Blush Tint.
- **Don't** animate on entry or scroll; motion answers touch only.
- **Don't** add a filter bar, results table, or photo-left list rows; the feed is a grid of photo-led cards.
- **Don't** add uppercase eyebrows or kickers above headings; Nunito weight carries hierarchy.
