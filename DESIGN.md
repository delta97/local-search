---
name: local-search
description: Self-hosted search and retrieval console — precision instrument for search, scrape, fetch, crawl, and map operations, with first-class run control and accessible interaction.
colors:
  forest-void: "#0e1512"
  forest-panel: "#141d19"
  forest-card: "#18231e"
  forest-deep: "#0c110f"
  ink: "#e8f0ea"
  ink-muted: "#7f948a"
  ink-dim: "#798d82"
  line: "#263630"
  harvest: "#f5b843"
  harvest-dim: "#b9862a"
  phosphor: "#56d99a"
  fault: "#e8705a"
typography:
  display:
    fontFamily: "Fraunces, Georgia, serif"
    fontSize: "30px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.5px"
  headline:
    fontFamily: "Fraunces, Georgia, serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.25
  title:
    fontFamily: "Fraunces, Georgia, serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "Space Mono, ui-monospace, monospace"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Space Mono, ui-monospace, monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: "0.09em"
rounded:
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "10px"
  xl: "12px"
  pill: "20px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "14px"
  lg: "22px"
components:
  button-primary:
    backgroundColor: "{colors.harvest}"
    textColor: "#10160f"
    rounded: "{rounded.md}"
    padding: "0 26px"
    typography: "{typography.label}"
  button-primary-hover:
    backgroundColor: "#ffca5c"
    textColor: "#10160f"
    rounded: "{rounded.md}"
    padding: "0 26px"
  button-primary-disabled:
    backgroundColor: "{colors.harvest-dim}"
    textColor: "#10160f"
    rounded: "{rounded.md}"
    padding: "0 26px"
  button-cancel:
    backgroundColor: "transparent"
    textColor: "{colors.ink-muted}"
    rounded: "{rounded.md}"
    padding: "0 25px"
    note: "the primary CTA morphs into this while a run is in flight"
  tab:
    backgroundColor: "transparent"
    textColor: "{colors.ink-muted}"
    rounded: "{rounded.md}"
    padding: "12px 20px"
  tab-active:
    backgroundColor: "{colors.forest-panel}"
    textColor: "{colors.harvest}"
    rounded: "{rounded.md}"
    padding: "12px 20px"
  pill:
    backgroundColor: "transparent"
    textColor: "{colors.ink-muted}"
    rounded: "{rounded.sm}"
    padding: "5px 11px"
  pill-active:
    backgroundColor: "rgba(245,184,67,0.08)"
    textColor: "{colors.harvest}"
    rounded: "{rounded.sm}"
    padding: "5px 11px"
  pill-disabled:
    opacity: 0.4
    note: "answer/summary pills when /healthz reports llm_configured: false"
  badge:
    backgroundColor: "transparent"
    textColor: "{colors.harvest}"
    rounded: "{rounded.pill}"
    padding: "3px 10px"
  input:
    backgroundColor: "{colors.forest-void}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "13px 15px"
---

# Design System: local-search

## 1. Overview

**Creative North Star: "The Instrument Panel"**

This is a precision instrument for autonomous retrieval — a developer console that sits between the user and a search-scrape-fetch-crawl-map infrastructure stack. The aesthetic philosophy is absolute: every pixel earns its place by conveying state, structure, or information. Nothing is decorative. Nothing shouts.

The palette is deep forest dark — not the blue-black of a generic IDE, not the purple-neon of cyberpunk. Green-black, like a terminal screen seen through a canopy. Harvest amber is the primary signal; Phosphor green marks liveness and success. A scanline texture overlay (fixed `body::before`, `repeating-linear-gradient` at 1.4% white opacity, 0.5 overall opacity) creates the CRT substrate that gives the surface a physical quality without becoming a costume. Radial amber and green halos ghost at the edges of the body background, anchoring the two accent families into the dark before a single component appears.

The typeface split is the system's single most deliberate decision: Fraunces (variable-optical, 500–600 weight) appears only on content that belongs to the user's data — search result titles, fetched/crawled document headings, history run labels, the product wordmark. Space Mono covers every word the interface itself speaks — buttons, labels, tabs, inputs, metadata, status. The two voices never cross. The result is that the machine's chrome disappears into the task, and what surfaces is the data.

What this system is not: it is not a SaaS dashboard with warm beige backgrounds, gradient text CTAs, hero metrics, or identical rounded-card grids. There is no marketing mode, no onboarding flow, no persistent empty state illustration, no modal-first interaction pattern. The user arrives already in a task, and every disclosure, confirmation, and status update happens inline.

**Key Characteristics:**
- Monospace-native: Space Mono for all interface text — labels, inputs, tabs, buttons, metadata, status
- Serif contrast: Fraunces appears only at the content tier — result titles, document headings, history run labels, the product name
- Amber-as-signal: Harvest marks active states, primary CTAs, and live progress
- Tonal depth: four surface levels (Forest Void → Forest Panel → Forest Card → Forest Deep), no decorative shadows
- Scanline substrate: a fixed `::before` texture creates the console grain
- Runs are jobs, not fire-and-forget requests: every search/fetch/crawl/map has a first-class running state, a cancel affordance, and survives a page refresh
- Accessible by construction, not by overlay: real `<button>` disclosures, a WAI-ARIA tablist, one polite live region, and a universal keyboard-focus ring

## 2. Colors

A committed dark palette anchored in a green-black base, with two functional accent families (amber and phosphor) and a strict semantic vocabulary. Every color below is a CSS custom property in `:root`; a small, named set of off-ramp literals exists for specific, documented reasons (see **Off-Palette Exceptions**).

### Primary
- **Harvest Gold** (`#f5b843`, `--amber`): The sole CTA color and primary active-state indicator. Applied to the primary button background, active tab text, active pill text and border, link colors within rendered markdown, and the running-state icon in the live progress log. Its scarcity is structural: every harvest appearance answers "what is currently active or ready to act."
- **Harvest Dim** (`#b9862a`, `--amber-dim`): The subordinate amber — hover-state borders on pills and inputs, the ambient focus glow carrier, blockquote borders in markdown, the disclosure-arrow color at rest. Never used as a standalone fill at rest. Always the pre-signal state of Harvest.

### Secondary
- **Phosphor Green** (`#56d99a`, `--green`): Live-status indicator (the pulsing header dot and the running-tab dot), success step icons in the progress log, URL display color in result and page cards, and "ok" status in history. Its job is distinct from Harvest's: where Harvest means "act here," Phosphor means "this is running" or "this succeeded."
- **Fault Red** (`#e8705a`, `--red`): Errors only. Error-settled step icons (a red ✕, never a green check, on any step that carried `level: "error"`), friendly failure summaries, gateway-unreachable status, history-run error state, delete-button hover/danger pills.

### Neutral
- **Forest Void** (`#0e1512`, `--bg`): Body background. The floor of the system. Also the input field background — inputs sit at the deepest surface so entered text reads as "below" the panel chrome.
- **Forest Panel** (`#141d19`, `--panel`): Primary panel surface. The active tab background merges with this intentionally.
- **Forest Card** (`#18231e`, `--panel-2`): Result cards, history cards, and output-panel surfaces. Slightly lifted from the panel.
- **Forest Deep** (`#0c110f`, hard-coded — see Off-Palette Exceptions): Code block, `<pre>`, and raw-JSON backgrounds. The darkest accessible surface; code sits in its own well below the card surface.
- **Ink** (`#e8f0ea`, `--ink`): Primary text. Slightly green-tinted white — not pure white, not gray. It belongs to the forest palette.
- **Ink Muted** (`#7f948a`, `--muted`): Secondary text: labels, metadata, inactive states, help/hint copy, disabled-pill text.
- **Ink Dim** (`#798d82`, `--ink-dim`): Placeholder text, step timestamps, output-panel byte/char sizes. Recomputed during the accessibility pass — see **Ink Dim: Contrast Fix** below.

### Off-Palette Exceptions
A handful of color literals exist outside the `:root` token set. Each is deliberate and scoped; none is a stray. They are documented here as sanctioned exceptions rather than silently tolerated debt — a future token pass could promote the recurring ones (`#0c110f`, `#cdd9d2`) to `--forest-deep` / `--ink-soft` tokens, but nothing here is accidental drift.

| Literal | Where | Why it's not a token |
|---|---|---|
| `#0c110f` | `.hrun .hdetail pre`, `.md code`, `.md pre` backgrounds | The "code well" background, one step darker than Forest Card. Used consistently (4 sites) — the strongest candidate for a future `--forest-deep` token. |
| `#cdd9d2` | `.obody pre.oraw`, `.md` body text | A soft off-white for dense raw/rendered text bodies, distinct from `--ink` (reserved for titles/labels) so long-form scraped content reads slightly quieter. Used consistently (3 sites). |
| `#b9c7bf` | `.card .snippet` | Search-result snippet text — a cooler, slightly dimmer neutral than `--ink` or `--muted`, tuned for long prose at small size. |
| `#ffca5c` | `button.go:hover` | The brightened hover state of Harvest Gold. A one-off "lighten on hover" value with no other use; not promoted to a token because no other component hovers to a brighter amber. |
| `rgba(0,0,0,.12)` | `.ohead` background | A near-black wash distinguishing the output-panel header strip from its body, independent of the panel/card token pair (it needs to work as an overlay tint, not a flat surface color). |
| `rgba(0,0,0,.7)` | `--shadow` (panel drop shadow) | Documented in §4 Elevation as the one structural shadow; kept as a raw rgba because it's a shadow color, not a surface. |
| `#10160f` | Primary button text | Near-black text-on-amber; distinct enough from `--bg` that it isn't the same role and doesn't warrant a shared token. |
| `rgba(245,184,67,*)` / `rgba(232,112,90,*)` | Hover/active washes, focus glow, disabled-danger borders | Alpha-varied washes of `--amber` / `--red` respectively — these are opacity treatments of existing tokens, not new colors, and are treated as in-palette. |

### Named Rules
**The One Signal Rule.** Harvest appears on a small, closed set of UI categories: active/current-selection states, the primary CTA button, live-progress indicators, and disclosure chevrons. It does not appear on decorative elements, hover-only states at full opacity, or secondary data. Every harvest appearance is answering a question — "what's active?" or "what's running?"

**The Domain Rule (color edition).** Phosphor and Harvest never compete for the same role. Phosphor = confirmed and live; Harvest = selected and primary. Success states use Phosphor. Active-navigation states use Harvest.

### Ink Dim: Contrast Fix

`--ink-dim` was previously `#52655c`, which measured 2.6–2.97:1 against the system's three dark surfaces — well under WCAG AA's 4.5:1 body-text minimum, despite carrying real content (placeholder text, step timestamps). It is now `#798d82`, computed (not guessed) to clear AA on all three surfaces it appears against, while staying visibly dimmer than `--ink-muted` in the same desaturated sage family:

| Surface | Hex | Contrast vs. `--ink-dim` (#798d82) |
|---|---|---|
| Forest Void (`--bg`) | `#0e1512` | **5.24:1** |
| Forest Panel (`--panel`) | `#141d19` | **4.88:1** |
| Forest Card (`--panel-2`) | `#18231e` | **4.58:1** |

For reference, `--ink-muted` (`#7f948a`) measures 5.01–5.73:1 across the same three surfaces — `--ink-dim` sits just above the AA floor while `--ink-muted` sits comfortably above it, preserving the two-tier muted hierarchy the system depends on.

## 3. Typography

**Display font:** Fraunces (variable optical size, weight 500–600), with Georgia, serif as fallback
**UI font:** Space Mono (400, 700), with ui-monospace, monospace as fallback
**No third typeface.** No sans-serif. No icon font (Lucide ships as inline SVG).

**Character:** The pairing is chosen for maximum contrast on a single axis — variable humanist serif vs. strict technical monospace. Fraunces is expressive and content-driven; Space Mono is neutral and data-dense. Their collision at the content tier (Fraunces result title above Space Mono metadata) is the intended effect: the user's retrieved data has warmth; the machine's readout does not.

### The Type Ramp (as-built)

The file carries fourteen distinct `font-size` literals. Rather than pretend the system is a clean four-step scale, this ramp documents and ratifies what actually ships: a **content tier** (three Fraunces sizes, on a roughly 1.33× step), a **body tier** (one size), and a wide **chrome/meta tier** (Space Mono, 10–13.5px) where most of the literal count lives — small UI text has many close-but-distinct roles (a step timestamp is not a stage label is not a badge is not a hint), and each earned its own value rather than being forced onto a shared one. This is ratified as the documented ramp, not flagged as drift: every value below has an assigned role, and no two roles collapse onto the same pixel value by accident.

**Content tier (Fraunces):**
| Size | Role |
|---|---|
| 30px | Display — product wordmark (h1). One instance per page. |
| 24px | Headline — fetched/crawled document title (`.doc h2`). |
| 18px | Title — search result card titles (`.card a.title`). |
| 15.5px | History run label (`.hrun .hlabel`) — Fraunces at content scale, but sized down to sit inline in a metadata row. |

**Body tier (Space Mono):**
| Size | Role |
|---|---|
| 15px | Input text value — the one true "body" size; everything else in the UI voice is smaller. |

**Chrome / meta tier (Space Mono, descending):**
| Size | Role |
|---|---|
| 14px | Primary button label (`button.go`); rendered markdown body (`.md`). |
| 13.5px | Search-result snippet text (`.card .snippet`). |
| 13px | Tab label; option-row text (`.opt`); status line; output-panel body (`.obody`). |
| 12.5px | Subhead byline (`.sub`); step-log row text (`.steps`); raw-output monospace body (`.oraw`); output-panel link list; inline `<code>` in rendered markdown. |
| 12px | Header health readout; card rank numeral; card URL; history detail `<pre>`; disclosure-header label. |
| 11.5px | Pill label; history metadata row; footer credit line; collapsed raw-error `<pre>`. |
| 11px | Form field label (uppercase, tracked); field validation note; option label (uppercase, tracked); step timestamp; post-run note. |
| 10.5px | Step stage label (uppercase, tracked); history "kind" tag; badge text; keyboard-hint `<kbd>`. |
| 10px | Small pill variant (`.pill.sm`) — the floor of the ramp; used only for compact inline actions (attach/cancel/rerun/confirm pills in history rows). |

**One-off exceptions (not part of the ramp, scoped to a single non-chrome context):** none remain — the `.sub`, `.snippet`, and `.hlabel` sizes that were historically ad hoc off-ramp values are now folded into the tiers above as named, single-purpose roles rather than treated as debt.

### Hierarchy
- **Display** (Fraunces, 600, 30px, line-height 1.2, -0.5px letter-spacing): Product wordmark (h1). Never reused for section headings.
- **Headline** (Fraunces, 600, 24px, line-height 1.25): Fetched/crawled document title in the Fetch and Crawl result panels. Signals "this is the document the user requested."
- **Title** (Fraunces, 600, 18px, line-height 1.3): Search result card titles. The content tier of the search panel. Hover state shifts to Harvest.
- **Body** (Space Mono, 400, 15px, line-height 1.5): Input text values, main form content.
- **Label** (Space Mono, 400, 11px, uppercase, 0.09em letter-spacing): Form field labels, option labels. Always uppercase. Always tracked. The machine's voice.
- **Meta** (Space Mono, 400, 10–13.5px, sentence case): Status messages, timestamps, scores, result metadata rows, step-log entries, pills, badges — the wide chrome/meta tier described above.

### Named Rules
**The Domain Rule.** Fraunces appears where the user's data lands (titles they searched for, documents they fetched or crawled, history run labels, the product name). Space Mono appears where the interface itself speaks (buttons, labels, inputs, status). These domains never cross: a CTA button is never set in Fraunces; a search result title is never set in Space Mono.

**History labels are a Domain Rule artifact, not a violation.** History run labels (`.hrun .hlabel`) render in Fraunces because a run's label is user-supplied content (a query, a URL) that the history list is displaying, not chrome describing itself — consistent with the rule, even though it sits inside an otherwise Space Mono-heavy row.

## 4. Elevation

This system uses tonal layering, not drop shadows, as its primary depth language. Four progressively distinct forest-black surfaces create physical separation without any shadow on individual content elements: Forest Void (floor) → Forest Panel (primary surface) → Forest Card (nested content) → Forest Deep (code wells). The eye reads these as stacked planes.

One structural shadow exists: `0 24px 60px -20px rgba(0,0,0,.7)` on the main content panel. This is a permanent gravitational undercast — not a hover-lift, not an interactive response. It declares the panel has mass. No other element in the system uses a drop shadow.

### Shadow Vocabulary
- **Panel Shadow** (`0 24px 60px -20px rgba(0,0,0,.7)`, `--shadow`): The main content panel only. Permanent; does not respond to state.
- **Focus Glow — mouse/programmatic** (`0 0 0 3px rgba(245,184,67,.12)`): Applied to focused inputs via `:focus`. Not elevation — state indicator using the Harvest hue family at low opacity.
- **Focus Glow — keyboard** (`:focus-visible` harvest ring, see §6 Accessibility): a stronger two-part treatment — `outline: 2px solid var(--amber)` at 2px offset, plus `box-shadow: 0 0 0 3px rgba(245,184,67,.15), 0 0 14px rgba(245,184,67,.35)` — applied globally to every interactive element, keyboard-triggered focus only.

### Named Rules
**The Floor Rule.** Shadows do not represent hover states, interaction feedback, or lifted components. The one panel shadow is a static declaration of structural depth. Interactive state is communicated through color (Harvest for active, Phosphor for success), never shadow lift.

## 5. Components

### Tabs (WAI-ARIA Tablist)
Five tabs navigate Search, Fetch page, Crawl, Map, and History. The tab row sits above the panel with no visible connector; the active tab's border colors and background merge it with the panel below.

Tabs are a real WAI-ARIA tablist, not just styled buttons: `role="tablist"` on the row, `role="tab"` + `aria-selected` + roving `tabindex` (0 on the active tab, -1 on the rest) on each tab, `role="tabpanel"` + `aria-labelledby` on each panel. Left/Right arrow keys move focus and activate the neighboring tab; Home/End jump to the first/last tab. Switching to History triggers a fresh `loadHistory()` fetch.

- **Shape:** 8px radius on top corners only (`8px 8px 0 0`); bottom radius is 0
- **Default:** transparent background, Ink Muted text, 1px transparent border
- **Active:** Forest Panel background, Harvest text, 1px Line border on top/left/right, no bottom border (merges with panel)
- **Hover:** Ink text, no fill change
- **Live indicator:** a small pulsing Harvest dot (`.livedot`) appears on the History tab whenever `GET /jobs` reports one or more runs in flight — the tablist itself reports live state, not just the running panel.
- **Focus:** the universal keyboard focus-visible glow (see §6)

### Buttons
One primary variant (`.go`), plus a state-morph and small icon/danger pills (see Pills below).
- **Shape:** 8px radius (rounded.md)
- **Primary fill:** Harvest Gold (`#f5b843`)
- **Text:** `#10160f` (near-black), 700 weight, 14px, uppercase, 0.06em letter-spacing (Label register)
- **Hover:** `#ffca5c` (brighter amber, off-palette — see §2 Off-Palette Exceptions), no size or shadow change
- **Active:** `translateY(1px)` — a 1px physical press; color unchanged
- **Disabled:** Harvest Dim fill, 0.7 opacity, `cursor: wait`
- **Focus:** universal keyboard focus-visible glow

**Cancel morph (`.go.go-cancel`).** Because every run is now a first-class server-side job, the primary CTA is not a one-shot fire button — it morphs in place into a cancel affordance the instant the job is accepted (`msg.type === "job"`): transparent background, Ink Muted text/border, label swapped to "cancel", `aria-label` set to `cancel this {kind} run`. Hover shifts to a red wash (`rgba(232,112,90,.06)` background, Fault border/text). Clicking it disables the button, shows "cancelling…", and posts `/jobs/{id}/cancel`; if the network call itself fails, the client at minimum aborts its own SSE stream. The button reverts to its original submit state (`restoreBtn()`) once the run reaches a terminal state — result, error, or cancelled.

### Inputs / Fields
- **Style:** Forest Void background, 1px Line border, 8px radius, 13px 15px padding
- **Text:** Ink at 15px (Space Mono)
- **Placeholder:** Ink Dim (`#798d82`)
- **Focus (mouse/programmatic):** border shifts to Harvest Dim, `0 0 0 3px rgba(245,184,67,.12)` glow
- **Focus (keyboard):** additionally picks up the universal `:focus-visible` harvest ring
- **Transitions:** 0.15s on border-color and box-shadow
- **Persistence:** per-panel option values (not the primary query/URL input) are saved to `localStorage` on every `input`/`change` and restored on load — see §6.

### Pills
Used for time-range selectors, view toggles (cards/json), sitemap mode, answer mode, action controls (refresh, clear, attach, cancel, rerun, delete-confirm), and disclosure-adjacent affordances.
- **Shape:** 6px radius (rounded.sm); a small variant (`.pill.sm`, 10px text) is used for compact inline row actions
- **Default:** transparent background, Ink Muted text, 1px Line border
- **Hover:** Ink text, Harvest Dim border
- **Active:** Harvest text, Harvest Dim border, `rgba(245,184,67,.08)` fill
- **Danger** (`.pill.danger`): Fault text, translucent Fault border at rest, solidifying + tinted background on hover — used for the cancel and delete-confirm pills
- **Disabled** (`.pill:disabled`): 0.4 opacity, no hover response — used on the "basic"/"advanced" answer pills when `/healthz` reports `llm_configured: false` (see §7)
- **Transitions:** 0.15s on color, border-color, background

### Badges
Compact metadata labels used inline with result titles ("scraped"), the Fetch/Crawl result header (format identifiers, geo indicator, stealth flag), PDF page counts, and HTTP status codes.
- **Shape:** 20px radius (pill)
- **Style:** Harvest text, Harvest Dim border, transparent background
- **Text:** 10.5px Space Mono, uppercase, 0.08em letter-spacing

### Result Cards
The core content atom of the Search, Fetch-batch, Crawl, and Map panels.
- **Shape:** 10px radius, Forest Card background, 1px Line border, 16px 18px internal padding
- **Entrance:** `rise` animation (translateY 8px → 0, opacity 0 → 1, 0.35s ease), staggered per card
- **Internal hierarchy:** Harvest Dim rank numeral → Fraunces title (hover to Harvest) → Phosphor URL → snippet text (`#b9c7bf`) → Ink Muted metadata row
- **Expanded detail:** a disclosure button (`.ocollapse-head`, see §6) reveals a nested output-panel with per-format tabs (copy/download actions), Forest Deep code-block backgrounds inside

### History Cards
Structurally close to Result Cards with additional interactive states:
- **Disclosure:** the whole info row is a real `<button class="hexpand">` with `aria-expanded` / `aria-controls`, not a clickable `<div>` — keyboard- and screen-reader-operable. Row actions (rerun/delete, or attach/cancel for running jobs) sit beside the disclosure button, not inside it, so nested interactive elements stay valid HTML.
- **Status indicator:** Phosphor ("ok"), pulsing Harvest + spinner ("running"), Ink Muted ("cancelled"), Fault ("error") in the metadata row
- **Running-job actions:** an `attach` pill re-opens the live SSE stream for a job still in flight (re-attach after refresh), and a `cancel` pill posts the same cancel endpoint as the in-panel CTA
- **Completed-run actions:** a `rerun` pill loads the run's recorded request back into the matching panel's form (never auto-submits) and switches tab; an icon-only delete button (`aria-label`) triggers a two-step inline confirm
- **Two-step confirm pills:** both per-row delete and "clear all" replace the destructive control in place with a `confirm` / `keep` pill pair (auto-reverting after ~5–6s if left alone) — no `window.confirm`, no modal
- **Entrance discipline:** the `rise` animation fires only for runs not already seen this session (`.hnew`), so revisiting the History tab doesn't replay entrance animation on every card

### Live Step Log
An inline progress feed rendered into a `.status` container during active search/fetch/crawl/map operations, and replayed (from stored events) inside a History card's detail disclosure.
- **Running step:** spinning Harvest icon, Ink Muted text body, Harvest Dim stage label, Ink Dim timestamp
- **Settled step (success):** Phosphor checkmark, same text layout (`.donestep`)
- **Settled step (error):** the step settles with a red ✕ (`.errstep`), never a green check — driven by an optional `level: "error"` carried on the progress event from the gateway, not inferred client-side
- **Final success step:** Ink-colored text, Phosphor checkmark
- **Final error step:** one friendly, failure-class-specific summary line (`friendlyError()` — anti-bot, timeout, DNS, unreachable, upstream 5xx, 404, missing LLM key, PDF, empty-result classes each get a distinct one-liner) with the verbatim raw error kept in a collapsed `<details><summary>raw error</summary>`
- **Final cancelled step:** a calm, non-error final state (`.cancelstep`, stop-icon, muted color) — cancellation is not styled as failure
- **Replayed history timeline:** each stored event renders with the fault icon/red styling if it carried `level: "error"` server-side, so a replayed run's timeline matches how the live log actually settled each step

### Signature: The Panel Shell
The outer container that wraps every tab's content.
- **Shape:** 12px radius on three corners; top-left is 0 because the active tab connects there
- **Background:** Forest Panel (`#141d19`)
- **Border:** 1px Line
- **Shadow:** The single structural drop shadow (`0 24px 60px -20px rgba(0,0,0,.7)`)
- **Padding:** 26px (16px at ≤640px — see §7 Mobile)

## 6. Accessibility

Accessibility is treated as a construction concern, not a bolt-on layer — every pattern below replaced a visually-identical but semantically-inert version of itself.

**Real disclosure buttons.** Every expand/collapse control in the system — scraped-output collapse (`.ocollapse-head`), page-content collapse on batch/crawl cards, and the whole History-row info disclosure (`.hexpand`) — is a real `<button>` with `aria-expanded` toggling true/false and `aria-controls` pointing at the region it reveals. None of these were clickable `<div>`s; keyboard `Tab` + `Enter`/`Space` operate all of them identically to a mouse click.

**WAI-ARIA tablist.** See §5 Tabs — full `role="tablist"`/`role="tab"`/`role="tabpanel"` wiring with `aria-selected`, roving `tabindex`, and Left/Right/Home/End arrow-key navigation.

**Single-line live region.** `#srStatus` (`role="status"`, `aria-live="polite"`, `aria-atomic="true"`, visually hidden via `.sr-only`) announces run-phase changes and final outcomes only — run started, one announcement per stage change (not every progress line), and the terminal result/cancelled/failed state. The design intentionally does not mirror the full step log into the live region: a screen-reader user gets a coherent narration, not a firehose.

**`aria-label` on icon-only controls.** Every icon-only button (per-row history delete, attach/cancel/rerun pills, delete-confirm/keep pills) carries a descriptive `aria-label` — e.g. `load this run's parameters into the {kind} form`, `cancel this {kind} run`.

**Universal `:focus-visible` harvest glow.** One consistent, branded keyboard-focus indicator applies to every interactive element — links, buttons, inputs, selects, textareas, `<summary>`, `[tabindex]`, tabs, and disclosure buttons: a 2px solid Harvest outline at 2px offset, plus a soft two-layer amber box-shadow glow (`0 0 0 3px rgba(245,184,67,.15), 0 0 14px rgba(245,184,67,.35)`). It fires only on keyboard focus (`:focus-visible`, not `:focus`), so mouse interaction keeps the existing quieter input border treatment.

**`--ink-dim` contrast fix.** See §2 for the full before/after — recomputed to `#798d82`, clearing WCAG AA (≥4.5:1) against all three surfaces it's used on, while remaining visually distinct from and dimmer than `--ink-muted`.

**`prefers-reduced-motion`.** A single media-query block neutralizes the scanline/rise/pulse/glow/spin motion system-wide (`animation-duration`/`transition-duration` forced to `.001ms`, `animation-iteration-count: 1`, `scroll-behavior: auto`), with an explicit carve-out to keep the live-status dot and tab live-dot visible at full (non-pulsing) opacity rather than freezing them mid-fade.

**Keyboard accelerators.** `/` focuses the active panel's primary input (query/URL) when focus isn't already in a form control; `Cmd`/`Ctrl`+`Enter` submits the active panel's form from anywhere. Both are documented in a persistent footer hint (`<kbd>` styled keys). Neither accelerator fires while the user is actively typing in an input/textarea/select or a `contenteditable`, except the Enter accelerator, which is meant to work from inside the form.

**Rerun-from-history.** The `rerun` pill on a completed history row reads that run's recorded request JSON and repopulates the matching panel's form fields, checkboxes, and pill groups (`fillForm()`) — then switches tab and focuses the primary input, but never auto-submits. If a recorded answer-mode pill (`basic`/`advanced`) would land on a pill currently disabled by a missing LLM key, it falls back to `off` instead of restoring an unusable active state.

**Per-panel persistence.** Non-primary option values (checkboxes, selects, pill groups) for each of the four run panels are saved to `localStorage` (`ls.panel.{kind}`) on every change and restored on page load. Primary query/URL inputs are deliberately excluded from persistence — a returning user gets their tuned options back without an unwanted pre-filled query.

## 7. Mobile / Narrow Viewport

A single `@media (max-width: 640px)` block adapts layout structurally — no font-size shrinking, so the type ramp in §3 holds at every breakpoint:
- Tabs become a horizontally-scrolling strip with 44px-minimum touch targets (scrollbar hidden) instead of wrapping or overflowing.
- The primary query/URL row stacks the field above a full-width, 44px-minimum CTA instead of squeezing a fixed-width button beside a shrinking input.
- Option rows that were two-up (e.g. include/exclude domains, include/exclude tags, crawl path filters) drop to one-per-line with the label stacked above its input.
- The nested "scrape as" checkbox group and the header health readout wrap instead of overflowing.
- Long unbroken strings (snippets containing bare URLs) wrap via `overflow-wrap: anywhere` instead of widening their card.
- History metadata is allowed to wrap rather than forcing the row wider than the panel.

## 8. Do's and Don'ts

### Do:
- **Do** use Fraunces exclusively on content the user retrieved or supplied: search result titles, fetched/crawled document titles, history run labels, and the product wordmark. These are the only Fraunces contexts.
- **Do** use Harvest (`#f5b843`) only for active/current-selection states, the primary CTA button, live-progress step icons, and disclosure chevrons. Harvest at full opacity on anything else undermines the signal.
- **Do** maintain the four-level surface ramp strictly: Forest Void (body/inputs), Forest Panel (primary surface), Forest Card (cards/nested/output panels), Forest Deep (code blocks). No fifth level.
- **Do** use the universal `:focus-visible` harvest glow as the keyboard-focus treatment on every interactive element. No colored outlines, no blue default rings, no element left out of the ring.
- **Do** settle an error-bearing progress step with the fault icon (red ✕), never a green check — this is driven by the event's `level` field, not inferred from timing or guesswork.
- **Do** give every destructive action (delete, clear-all) an inline two-step confirm; never a `window.confirm` or a modal.
- **Do** ship every interactive component with all its applicable states: default, hover, focus, active, disabled, and — for run-driving controls — running/cancel.
- **Do** respect `prefers-reduced-motion` for every animation and transition in the system, with the sole carve-out of keeping live-status indicators visibly "on" rather than motion-frozen mid-fade.

### Don't:
- **Don't** introduce any warm-neutral, light-mode, or near-white background. This is a committed dark system. SaaS dashboard beige, paper white, warm-sand backgrounds, and parchment-tinted surfaces are explicitly prohibited.
- **Don't** use gradient text (`background-clip: text`). Color carries semantic meaning here; decorative gradients dilute every color role.
- **Don't** add a third typeface. The Fraunces/Space Mono axis is complete. No sans-serif, no display grotesque, no editorial serif variant.
- **Don't** use Fraunces on buttons, labels, form controls, status messages, tabs, or any UI chrome. It belongs to the data layer, not the machine layer.
- **Don't** add drop shadows to result cards, history cards, or any repeated content element. The single structural panel shadow is not a motif — it is a one-time declaration.
- **Don't** build hero-metric tiles, big-number stat cards, or dashboard aggregate views. This is an instrument panel that surfaces retrieved data, not a SaaS analytics screen.
- **Don't** use full-opacity Harvest on inactive or decorative elements. Inactive contexts use Harvest Dim or transparency. Full Harvest is reserved for the current active signal only.
- **Don't** invent non-standard affordances for standard patterns. No custom scrollbars, no styled `<select>` popover replacements, no modal-first patterns where inline progressive disclosure or an inline confirm pill works.
- **Don't** show internal infrastructure hostnames (`api:3002`, `camoufox:3000`, `searxng:8888`) to the user, in any error string, health readout, or progress message — the gateway rewrites these to friendly service names (`scrape engine`, `browser engine`, `search engine`) before any human-readable string leaves it. Response shapes/keys are never touched by this rewrite.
- **Don't** mirror the full progress log into the screen-reader live region — one line, phase changes and terminal state only.
- **Don't** leave a run's cancel/attach affordance un-labelled — icon-only controls always carry `aria-label`.
