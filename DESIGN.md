---
name: local-search
description: Self-hosted search and retrieval console — precision instrument for search, scrape, and fetch operations.
colors:
  forest-void: "#0e1512"
  forest-panel: "#141d19"
  forest-card: "#18231e"
  forest-deep: "#0c110f"
  ink: "#e8f0ea"
  ink-muted: "#7f948a"
  ink-dim: "#52655c"
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
  md: "16px"
  lg: "24px"
  xl: "40px"
components:
  button-primary:
    backgroundColor: "{colors.harvest}"
    textColor: "#10160f"
    rounded: "{rounded.md}"
    padding: "13px 26px"
    typography: "{typography.label}"
  button-primary-hover:
    backgroundColor: "#ffca5c"
    textColor: "#10160f"
    rounded: "{rounded.md}"
    padding: "13px 26px"
  button-primary-disabled:
    backgroundColor: "{colors.harvest-dim}"
    textColor: "#10160f"
    rounded: "{rounded.md}"
    padding: "13px 26px"
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

This is a precision instrument for autonomous retrieval — a developer console that sits between the user and a search-scrape-fetch infrastructure stack. The aesthetic philosophy is absolute: every pixel earns its place by conveying state, structure, or information. Nothing is decorative. Nothing shouts.

The palette is deep forest dark — not the blue-black of a generic IDE, not the purple-neon of cyberpunk. Green-black, like a terminal screen seen through a canopy. Harvest amber is the primary signal; Phosphor green marks liveness and success. A scanline texture overlay (fixed `::before`, ~1.4% opacity) creates the CRT substrate that gives the surface a physical quality without becoming a costume. Radial amber and green halos ghost at the edges of the body background, anchoring the two accent families into the dark before a single component appears.

The typeface split is the system's single most deliberate decision: Fraunces (variable-optical, 500–600 weight) appears only on content that belongs to the user's data — search result titles, fetched document headings, the product wordmark. Space Mono covers every word the interface itself speaks — buttons, labels, tabs, inputs, metadata, status. The two voices never cross. The result is that the machine's chrome disappears into the task, and what surfaces is the data.

What this system is not: it is not a SaaS dashboard with warm beige backgrounds, gradient text CTAs, hero metrics, or identical rounded-card grids. There is no marketing mode, no onboarding flow, no persistent empty state illustration. The user arrives already in a task.

**Key Characteristics:**
- Monospace-native: Space Mono for all interface text — labels, inputs, tabs, buttons, metadata, status
- Serif contrast: Fraunces appears only at the content tier — result titles, document headings, the product name
- Amber-as-signal: Harvest marks exactly three categories — active states, primary CTAs, live progress
- Tonal depth: four surface levels (Forest Void → Forest Panel → Forest Card → Forest Deep), no decorative shadows
- Scanline substrate: a fixed `::before` texture at 0.5× opacity creates the console grain

## 2. Colors

A committed dark palette anchored in a green-black base, with two functional accent families (amber and phosphor) and a strict semantic vocabulary.

### Primary
- **Harvest Gold** (`#f5b843`): The sole CTA color and primary active-state indicator. Applied to the primary button background, active tab text, active pill text and border, link colors within rendered markdown, and the running-state icon in the live progress log. Its scarcity is structural: every harvest appearance answers "what is currently active or ready to act."
- **Harvest Dim** (`#b9862a`): The subordinate amber — hover-state borders on pills and inputs, the ambient focus glow carrier, blockquote borders in markdown. Never used as a standalone fill at rest. Always the pre-signal state of Harvest.

### Secondary
- **Phosphor Green** (`#56d99a`): Live-status indicator (the pulsing dot in the header), success step icons in the progress log, URL display color in result cards, and "ok" status in history. Its job is distinct from Harvest's: where Harvest means "act here," Phosphor means "this is running" or "this succeeded."
- **Fault Red** (`#e8705a`): Errors only. Error step icons, failed scrape notifications, gateway-unreachable status, history-run error state, delete-button hover. Appears in no decorative context.

### Neutral
- **Forest Void** (`#0e1512`): Body background. The floor of the system. Also the input field background — inputs sit at the deepest surface so entered text reads as "below" the panel chrome.
- **Forest Panel** (`#141d19`): Primary panel surface. The active tab background merges with this intentionally.
- **Forest Card** (`#18231e`): Result cards and nested content surfaces. Slightly lifted from the panel.
- **Forest Deep** (`#0c110f`): Code block backgrounds. The darkest accessible surface; code sits in its own well below the card surface.
- **Ink** (`#e8f0ea`): Primary text. Slightly green-tinted white — not pure white, not gray. It belongs to the forest palette.
- **Ink Muted** (`#7f948a`): Secondary text: labels, metadata, inactive states, placeholder-adjacent contexts.
- **Ink Dim** (`#52655c`): Placeholder text. The minimum readable ink in this system.

### Named Rules
**The One Signal Rule.** Harvest appears on ≤3 UI categories: active/current-selection states, the primary CTA button, and live-progress indicators. It does not appear on decorative elements, hover-only states at full opacity, or secondary data. Every harvest appearance is answering a question — "what's active?" or "what's running?"

**The Domain Rule (color edition).** Phosphor and Harvest never compete for the same role. Phosphor = confirmed and live; Harvest = selected and primary. Success states use Phosphor. Active-navigation states use Harvest.

## 3. Typography

**Display font:** Fraunces (variable optical size, weight 500–600), with Georgia, serif as fallback
**UI font:** Space Mono (400, 700), with ui-monospace, monospace as fallback
**No third typeface.** No sans-serif. No icon font (Lucide ships as inline SVG).

**Character:** The pairing is chosen for maximum contrast on a single axis — variable humanist serif vs. strict technical monospace. Fraunces is expressive and content-driven; Space Mono is neutral and data-dense. Their collision at the content tier (Fraunces result title above Space Mono metadata) is the intended effect: the user's retrieved data has warmth; the machine's readout does not.

### Hierarchy
- **Display** (Fraunces, 600, 30px, line-height 1.2, -0.5px letter-spacing): Product wordmark (h1). One instance per page, never reused for section headings.
- **Headline** (Fraunces, 600, 24px, line-height 1.25): Fetched document title in the Fetch result panel. Signals "this is the document the user requested."
- **Title** (Fraunces, 600, 18px, line-height 1.3): Search result card titles. The content tier of the search panel. Hover state shifts to Harvest.
- **Body** (Space Mono, 400, 15px, line-height 1.5): Input text values, primary prose in fetched markdown, main UI content.
- **Label** (Space Mono, 400, 11px, uppercase, 0.09em letter-spacing): Form field labels, tab text, button text, pill text, option labels. Always uppercase. Always tracked. The machine's voice.
- **Meta** (Space Mono, 400, 11–12.5px, sentence case): Status messages, timestamps, scores, result metadata rows, step-log entries. Same family as Label, lower contrast presence.

### Named Rules
**The Domain Rule.** Fraunces appears where the user's data lands (titles they searched for, documents they fetched, the product name). Space Mono appears where the interface itself speaks (buttons, labels, inputs, status). These domains never cross: a CTA button is never set in Fraunces; a search result title is never set in Space Mono.

## 4. Elevation

This system uses tonal layering, not drop shadows, as its primary depth language. Four progressively distinct forest-black surfaces create physical separation without any shadow on individual content elements: Forest Void (floor) → Forest Panel (primary surface) → Forest Card (nested content) → Forest Deep (code wells). The eye reads these as stacked planes.

One structural shadow exists: `0 24px 60px -20px rgba(0,0,0,0.7)` on the main content panel. This is a permanent gravitational undercast — not a hover-lift, not an interactive response. It declares the panel has mass. No other element in the system uses a drop shadow.

### Shadow Vocabulary
- **Panel Shadow** (`0 24px 60px -20px rgba(0,0,0,0.7)`): The main content panel only. Permanent; does not respond to state.
- **Focus Glow** (`0 0 0 3px rgba(245,184,67,0.12)`): Applied to focused inputs and interactive elements. Not elevation — state indicator using the Harvest hue family at low opacity.

### Named Rules
**The Floor Rule.** Shadows do not represent hover states, interaction feedback, or lifted components. The one panel shadow is a static declaration of structural depth. Interactive state is communicated through color (Harvest for active, Phosphor for success), never shadow lift.

## 5. Components

### Tabs
Three tabs navigate Search, Fetch, and History. The tab row sits above the panel with no visible connector; the active tab's border colors and background merge it with the panel below.
- **Shape:** 8px radius on top corners only (`8px 8px 0 0`); bottom radius is 0
- **Default:** transparent background, Ink Muted text, 1px transparent border
- **Active:** Forest Panel background, Harvest text, 1px Line border on top/left/right, no bottom border (merges with panel)
- **Hover:** Ink text, no fill change
- **Focus:** Harvest focus glow

### Buttons
One variant — Primary (.go). No secondary or ghost variants currently exist.
- **Shape:** 8px radius (rounded.md)
- **Primary fill:** Harvest Gold (#f5b843)
- **Text:** #10160f (near-black), 700 weight, 14px, uppercase, 0.06em letter-spacing (Label register)
- **Hover:** #ffca5c (brighter amber), no size or shadow change
- **Active:** `translateY(1px)` — a 1px physical press; color unchanged
- **Disabled:** Harvest Dim fill, 0.7 opacity, `cursor: wait`
- **Focus:** Harvest focus glow

### Inputs / Fields
- **Style:** Forest Void background, 1px Line border, 8px radius, 13px 15px padding
- **Text:** Ink at 15px (Space Mono)
- **Placeholder:** Ink Dim (#52655c)
- **Focus:** border shifts to Harvest Dim, `0 0 0 3px rgba(245,184,67,0.12)` glow
- **Transitions:** 0.15s on border-color and box-shadow

### Pills
Used for time-range selectors, view toggles (cards/json), and action controls (refresh, clear).
- **Shape:** 6px radius (rounded.sm)
- **Default:** transparent background, Ink Muted text, 1px Line border
- **Hover:** Ink text, Harvest Dim border
- **Active:** Harvest text, Harvest Dim border, `rgba(245,184,67,0.08)` fill
- **Transitions:** 0.15s on color, border-color, background

### Badges
Compact metadata labels used inline with result titles ("scraped") and in the Fetch result header (format identifiers, geo indicator).
- **Shape:** 20px radius (pill)
- **Style:** Harvest text, Harvest Dim border, transparent background
- **Text:** 10.5px Space Mono, uppercase, 0.08em letter-spacing

### Result Cards
The core content atom of the Search panel.
- **Shape:** 10px radius, Forest Card background, 1px Line border, 16px 18px internal padding
- **Entrance:** `rise` animation (translateY 8px → 0, opacity 0 → 1, 0.35s ease), staggered 40ms per card
- **Internal hierarchy:** Harvest Dim rank numeral → Fraunces title (hover to Harvest) → Phosphor URL → Ink Muted snippet text → Ink Muted metadata row
- **Expanded detail:** dashed Line border separator at top, Forest Deep code block background

### History Cards
Structurally identical to Result Cards with additional interactive states:
- **Expand/collapse:** whole card is clickable; `.open` class shows the detail section
- **Status indicator:** Phosphor ("ok"), Fault ("error") in the metadata row
- **Delete button:** Ink Muted at rest, Fault on hover — appears inline in the card row

### Live Step Log
An inline progress feed rendered into `.status` containers during active search/fetch operations.
- **Running step:** spinning Harvest icon, Ink Muted text body, Harvest Dim stage label, dark muted timestamp
- **Settled step:** Phosphor checkmark, same text layout
- **Final success step:** Ink-colored text, Phosphor checkmark
- **Error step:** Fault throughout — icon, stage label, and body text all shift to Fault Red

### Signature: The Panel Shell
The outer container that wraps all three tab views.
- **Shape:** 12px radius on three corners; top-left is 0 because the active tab connects there
- **Background:** Forest Panel (#141d19)
- **Border:** 1px Line
- **Shadow:** The single structural drop shadow (`0 24px 60px -20px rgba(0,0,0,0.7)`)
- **Padding:** 26px

## 6. Do's and Don'ts

### Do:
- **Do** use Fraunces exclusively on content the user retrieved: search result titles, fetched document titles, and the product wordmark. These are the only Fraunces contexts.
- **Do** use Harvest (#f5b843) only for active/current-selection states, the primary CTA button, and live-progress step icons. Harvest at full opacity on anything else undermines the signal.
- **Do** maintain the four-level surface ramp strictly: Forest Void (body/inputs), Forest Panel (primary surface), Forest Card (cards/nested), Forest Deep (code blocks). No fifth level.
- **Do** use the focus glow — `0 0 0 3px rgba(245,184,67,0.12)` — as the universal focus treatment on all interactive elements. No colored outlines, no blue default rings.
- **Do** use the `rise` animation (translateY 8px → 0, opacity 0 → 1, 0.35s ease) for any new content that appears as a result of user action (search results, history entries, document panels).
- **Do** ship every interactive component with all five states: default, hover, focus, active, disabled. The current button and input are the canonical reference.

### Don't:
- **Don't** introduce any warm-neutral, light-mode, or near-white background. This is a committed dark system. SaaS dashboard beige, paper white, warm-sand backgrounds, and parchment-tinted surfaces are explicitly prohibited.
- **Don't** use gradient text (`background-clip: text`). Color carries semantic meaning here; decorative gradients dilute every color role.
- **Don't** add a third typeface. The Fraunces/Space Mono axis is complete. No sans-serif, no display grotesque, no editorial serif variant.
- **Don't** use Fraunces on buttons, labels, form controls, status messages, tabs, or any UI chrome. It belongs to the data layer, not the machine layer.
- **Don't** add drop shadows to result cards, history cards, or any repeated content element. The single structural panel shadow is not a motif — it is a one-time declaration.
- **Don't** build hero-metric tiles, big-number stat cards, or dashboard aggregate views. This is an instrument panel that surfaces retrieved data, not a SaaS analytics screen.
- **Don't** use full-opacity Harvest on inactive or decorative elements. Inactive contexts use Harvest Dim or transparency. Full Harvest is reserved for the current active signal only.
- **Don't** invent non-standard affordances for standard patterns. No custom scrollbars, no styled `<select>` popover replacements, no modal-first patterns where inline progressive disclosure works.
- **Don't** put the scanline texture or radial background halos on nested surfaces (panels, cards). The atmospheric background treatment belongs to the body layer only.
