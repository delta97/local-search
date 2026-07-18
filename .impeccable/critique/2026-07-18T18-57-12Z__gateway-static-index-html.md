---
target: gateway/static/index.html (web console)
total_score: 27
p0_count: 0
p1_count: 3
timestamp: 2026-07-18T18-57-12Z
slug: gateway-static-index-html
---
Method: dual-agent (A: design-review sub-agent · B: detector/browser-evidence sub-agent)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 4 | n/a — streamed step log with stage/elapsed is genuinely excellent; one nick: an error-bearing progress event settles with a green checkmark |
| 2 | Match System / Real World | 3 | "sitemap include/skip/only", regex path filters unexplained; raw backend errors leak internal hostnames (`http://api:3002/v2/scrape`) |
| 3 | User Control and Freedom | 2 | No cancel/abort for running ops (crawl budget up to 900s); no undo on history delete/clear; no rerun from history |
| 4 | Consistency and Standards | 3 | Focus treatment split: branded harvest glow on inputs, default UA ring on buttons/pills/tabs; DESIGN.md promises a universal glow |
| 5 | Error Prevention | 2 | "clear all" history is an instant permanent DELETE with no confirm; batch URLs silently truncated to 20; no unload guard mid-run |
| 6 | Recognition Rather Than Recall | 3 | Placeholders teach input formats well, but no recent-query recall and no way to reload a past run's parameters |
| 7 | Flexibility and Efficiency | 2 | Zero keyboard shortcuts (`/`, ⌘+Enter, tab cycling); no saved defaults; autofocus + Enter-submit are the only accelerators |
| 8 | Aesthetic and Minimalist Design | 4 | n/a — disciplined, distinctive, every pixel informational |
| 9 | Error Recovery | 2 | Failed fetch prints the same raw error 3× with no remediation hint, despite a stealth toggle sitting right there |
| 10 | Help and Documentation | 2 | Inline hints exist (footer API map, key warnings) but nothing explains stealth, sitemap modes, or depth/budget semantics |
| **Total** | | **27/40** | **Acceptable — solid working tool, held back by run-control, error UX, and responsiveness** |

## Anti-Patterns Verdict

**LLM assessment**: Not slop. The console has a coherent, held point of view: Fraunces serif reserved for retrieved data, Space Mono for all chrome, harvest amber genuinely scarce, tonal elevation instead of shadow spam. None of the banned patterns appear (no gradient text, glassmorphism, side-stripes, hero metrics, numbered scaffolding; the uppercase tracked labels are form labels doing real work, not eyebrows). Where it slips from Linear-quality is operational, not aesthetic: a broken 390px breakpoint and a raw, tripled error state.

**Deterministic scan**: 27 CLI findings across 3 rules in `gateway/static/index.html` — `overused-font` (Fraunces, 6 hits: lines 9, 52, 132, 148, 206, 213), `design-system-font-size` (18 literals off the DESIGN.md ramp: 10/12/12.5/13/13.5/14px), `design-system-color` (3: `#ffca5c` line 108, `#b9c7bf` line 151, `rgba(0,0,0,.12)` line 165). Runtime scan found 9 anti-pattern elements: dark-glow (status dot + body), repeating-stripes gradient on body, thin-border-wide-shadow on all five panels, 11px tiny text (`span.opt`), all-caps label text.

**Agreement/disagreement**: The detector's runtime hits (glow, scanline stripes, hairline-border-wide-shadow, caps labels) are largely the *intentional* CRT-instrument aesthetic that Assessment A independently judged restrained and purposeful — mostly false positives on intent, mechanically correct detections. The five panel shadow hits are one CSS rule counted five times. The genuinely actionable detector signal is **design-system drift**: 18 font-size literals and 3 colors outside DESIGN.md, corroborating Assessment A's finding that DESIGN.md and the implementation have diverged (spec says three tabs, app has five; promised universal focus glow unimplemented). The detector cannot see the highest-impact issues (no cancel, tripled errors, broken mobile) — those came only from the human-style review. Contrast measurement: `ink-dim #52655c` timestamps/helper text measure **2.77–2.97:1** — fails even the 3:1 large-text bar; all other token pairs pass comfortably (ink 14.8:1, muted 5.0–5.7:1, harvest 9.7:1, phosphor 9.1:1, fault 5.7:1).

**Visual overlays**: Injection succeeded — overlays are visible in the **[Human]** tab in Chrome, with a top banner listing body-level findings and badge tags pinned to offending elements (only the Search panel's tags are in-viewport; the other four panels are hidden tab panes). Console reported `[impeccable] 9 anti-patterns found`.

## Overall Impression

A designed instrument, not a template: the live SSE step log, the per-format output panels with copy/download/size, and the enforced serif-vs-mono domain rule give it a real voice. But it treats every run as a fire-and-forget form submission — no cancel, no rerun, no refresh survival — and it falls apart at exactly the two moments operators judge tools: failure (raw error tripled, one wearing a green checkmark) and mobile (158px of horizontal overflow at 390px). The single biggest opportunity: make runs first-class, controllable jobs.

## What's Working

1. **The live step log** (`makeStepLog` + SSE): stage labels, monotonic timestamps, spinner→check settlement. Better status visibility than most commercial tools; it makes a multi-service pipeline legible.
2. **The unified output-panel component** (`renderOutputPanels`): per-format tabs with byte sizes, copy/download everywhere, raw/rendered markdown toggle, reused identically across Fetch, Crawl, Map, and scraped search cards. Exactly what an operator feeding an LLM pipeline needs.
3. **Typographic discipline that survived implementation**: the Fraunces-for-data / Space Mono-for-chrome rule is actually true in the DOM. A stated design system the code obeys is rare.

## Priority Issues

1. **[P1] No way to cancel a running operation** — crawl/fetch/search have no abort; the only exit is a refresh, which orphans a run that keeps burning budget server-side (300s default, 900s max). Largest single trust gap for a power user. **Fix**: wire an `AbortController` to the SSE fetch, turn the disabled CTA into a cancel state, surface running jobs in History as "running". **Suggested command**: /impeccable harden
2. **[P1] Error state is raw, tripled, and mislabeled** — identical backend error rendered 3× (progress event settled with a *green check*, DONE step, final fail line); internal Docker URL leaks; a spurious "downloading (pdf path)" step runs against a dead domain. **Fix**: dedupe, use the fault icon on error events, one-line human summary ("couldn't scrape this site — try stealth mode") with the raw payload in a `<details>`. **Suggested command**: /impeccable clarify
3. **[P1] Narrow viewport is broken** — at 390px the document measures 548px (158px overflow); `.tabs` doesn't wrap or scroll (History unreachable without panning); `.row` squeezes the query input to 163px beside a full-size button. Violates the text-overflow ban outright. **Fix**: `@media (max-width: 640px)` — tabs wrap or `overflow-x:auto`, rows stack to column, full-width CTA. **Suggested command**: /impeccable adapt
4. **[P2] Destructive actions with no confirm or undo** — `#historyClear` fires `DELETE /history` instantly; per-row X deletes instantly; "clear all" sits adjacent to "refresh" with opposite stakes. **Fix**: confirm or 5s undo toast on clear-all; separate the two pills. **Suggested command**: /impeccable harden
5. **[P2] Keyboard/AT operability gaps** — `.ocollapse-head` disclosures and `.hrun` history cards are click-only `<div>`s (unreachable by keyboard); no `aria-live` on the step log or status; tab bar lacks tablist semantics; `ink-dim` text fails contrast at 2.77–2.97:1; focus ring style depends on element type. **Fix**: disclosure heads become `<button>`s, `aria-live="polite"` on status containers, global `:focus-visible` harvest glow, bump ink-dim toward the ink end. **Suggested command**: /impeccable audit

## Persona Red Flags

**Alex (Power User)**: No `/` to focus query, no ⌘+Enter, no tab-switch keys. No "rerun" on a History entry — must retype the query and re-tick every option. Format checkboxes reset on every reload. Cannot cancel the crawl he mis-launched.

**Sam (Accessibility-Dependent)**: Cannot open scraped-output disclosures or history run details at all via keyboard (div click handlers, no tabindex/keydown). Progress log never announced — a run is silent to a screen reader from submit to done. `ink-dim #52655c` timestamps fail the 3:1 large-text bar. Focus indicator depends on which element type you land on.

**Riley (Stress Tester)**: Empty query → silent no-op with zero feedback. Dead domain → the tripled-error valley plus a spurious follow-up step. Refresh mid-crawl → no `beforeunload` warning, live view gone, budget still burning. 25 batch URLs → silently sliced to 20. Map limit accepts 5000 links rendered as one giant flat `<ul>`.

## Minor Observations

- DESIGN.md drift (corroborated by the detector's 18 off-ramp font-size literals + 3 off-palette colors): spec documents three tabs, app has five; promised universal focus glow only exists on inputs. Worth a `/impeccable document` refresh.
- `loadHistory()` refires the fetch + `rise` entrance animation on every History tab visit — reads as flicker on revisit.
- History labels set URLs in Fraunces serif — the one place the Domain Rule produces an odd artifact.
- Header health readout exposes internal container hostname (`http://camoufox:3000`) in the most prominent screen position.
- "Answer" pills are offered even when `OPENROUTER_API_KEY` is absent — a discoverable dead end `/healthz` could preempt.
- Icon-only delete buttons rely on `title` only; `aria-label` would be sturdier.
- Scanline overlay and radial halos at ~1.4% opacity are restrained and stay off nested surfaces — good taste, not costume (the detector's dark-glow/stripes flags on `body` are mechanically correct but judged intentional).

## Questions to Consider

1. The primary consumer of this stack is an LLM agent over MCP — is the console's real job "human search UI" or "operator debugging a retrieval pipeline"? The latter prioritizes rerun-with-edits, request inspection, and cancellation over more search options.
2. A 300–900s crawl is a background job wearing a form's clothes. Should long runs become first-class jobs — visible as "running" in History, survivable across refresh, cancellable — instead of an SSE stream tethered to one tab?
3. Harvest amber is "the one signal" — the rule mostly holds today, but what enforces it at twice the feature count in a 1,000-line single file?
