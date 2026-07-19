# Impeccable critique → fix campaign: handoff

_Last updated: 2026-07-19. Waves 2 + 3 landed; only the final re-critique remains. See "Session 2026-07-19" below for current status; the rest of this file is kept as the historical record of the pause point._

## Context

`/impeccable critique` was run on the web console (`gateway/static/index.html`). Full report + backlog:
`.impeccable/critique/2026-07-18T18-57-12Z__gateway-static-index-html.md` — **score 27/40, 3× P1, 2× P2**.

The plan approved by the user: fix everything, in waves of parallel worktree agents, then re-critique.
Model policy per user: smallest capable model per task — Sonnet for mechanical, Opus for mid, Fable for architectural.

## ✅ Done (all merged into `main`)

| Pass | Branch | Commit | What landed |
|---|---|---|---|
| `adapt` (mobile, P1 #3) | `impeccable/adapt` | `6f075cd` | `@media (max-width:640px)`: scrollable tab strip (44px targets), stacked `.row` + full-width CTA, wrapped option rows (incl. `#scrapeFormats` — a second unwrapping row the critique missed), unwrapped `#health`, long-URL containment. Verified 0px horizontal overflow at 360/390/640/1024 across all 5 panels, incl. long-string stress test. |
| `harden` (run control, P1 #1 + P2 #4) | `impeccable/harden` | `258f929` | Runs are first-class server-side jobs: job registry over the existing `runs` table, seq-numbered event buffers, SSE replay + live tail, `GET /jobs`, `GET /jobs/{id}/stream`, `POST /jobs/{id}/cancel` (cancels asyncio task + upstream Firecrawl job; history write shielded). Client disconnect ≠ cancel. Console: CTA morphs to cancel, History shows running jobs w/ attach+cancel pills (pulsing amber dot), refresh-survival via re-attach, cancelled runs render calm final state, inline two-step confirms for clear-all & per-row delete (moved away from refresh), >20 batch-URL note instead of silent slicing. Verified end-to-end against the live stack. |
| Merge fix | — | `020e28b` | While agents ran, another session merged `feature/openrouter-navigate` (`10ef85d`) into main. Textual conflict in `app.py` resolved (kept `_summarize_counts` + harden's section comment) **plus a semantic conflict**: `/navigate` still called the removed `_run_recorded`; ported to harden's `_run_inline`. `pyflakes` clean. |

**Deploy note:** the gateway bakes code into its image (`build: ./gateway`) — `docker compose restart gateway` does NOT pick up `app.py` changes; use `docker compose up -d --build gateway`. Already rebuilt; `/jobs` + `/healthz` verified live on :8088. (Static `index.html` is served from disk in the container image too — also needs the rebuild.)

## ⏳ Not done as of 2026-07-18 (wave 2 + 3 — superseded, see Session 2026-07-19 below)

_Historical: at the 2026-07-18 pause, wave-2 agents had been launched then interrupted before writing any code. The plan below is kept for the record; all five items are now resolved — see the addendum._

1. **`/impeccable clarify`** (Opus) — error UX + copy. Scope: dedupe the tripled failure message; error-bearing progress events must settle with the fault icon, never the green check; per-failure-class one-line human summaries ("couldn't scrape this site — try stealth") with raw payload in a collapsed `<details>`; sanitize internal hostnames (`api:3002`, `camoufox:3000`) at the gateway (don't break MCP response shapes) and in the header health readout (friendly service names); kill the spurious "downloading (pdf path)" step after a fatal fetch error; empty-query submit → focus + inline hint (currently silent no-op); disable "answer" pills when no LLM key is configured (expose via `/healthz`); teaching copy for stealth / sitemap include-skip-only / depth vs pages vs budget / regex path filters (existing hint vocabulary, no tooltips framework, no modals). Firewall: don't touch aria-*, focus styles, tab semantics, `--ink-dim`, keyboard handlers, CSS media queries.
2. **`/impeccable audit`** (Opus) — keyboard/AT/contrast + Alex's accelerators. Scope: `.ocollapse-head` disclosures + `.hrun` cards → real buttons w/ `aria-expanded`; WAI-ARIA tablist pattern w/ arrow keys; `aria-label` on icon-only buttons; verify harden's new controls are keyboard-operable; `aria-live="polite"` status announcement (avoid SR spam — single updating status line beats the whole log); global `:focus-visible` harvest glow on ALL interactive elements; bump `--ink-dim` (#52655c, measures 2.77–2.97:1) to ≥4.5:1 against forest-void/panel/card (compute, don't guess; keep distinct from `--ink-muted`); `prefers-reduced-motion` block; `/` focuses active panel input, ⌘/Ctrl+Enter submits, footer hint; **rerun-from-history** pill (load recorded request params back into the form — see how harden's attach reads them); persist per-panel options to localStorage; fix History `rise` animation refiring on every tab visit. Firewall: `index.html` only, no error strings/health-readout copy, no `app.py`.
3. **`/impeccable polish`** (Fable, after 1+2 merge) — final pass on merged main with live browser verification (rebuild gateway first). Fix residuals; visually confirm mobile on the real running app (adapt's device-level check is still owed).
4. **`/impeccable document`** (Sonnet, last) — regenerate `DESIGN.md` from final code: five tabs not three, real type ramp (the 18 off-ramp literals: 10/12/12.5/13/13.5/14px — ratify or correct), off-palette colors (`#ffca5c`, `#b9c7bf`, `rgba(0,0,0,.12)`), new ink-dim value from audit, focus-glow behavior as implemented, plus harden's new components (cancel CTA, running badges, confirm pills).
5. Re-run **`/impeccable critique`** to measure the score against the 27/40 baseline (trend is tracked per-slug in `.impeccable/critique/`).

Smaller leftovers folded into the passes above: history URLs set in Fraunces serif (Domain Rule artifact), answer-pill dead end, `aria-label` on deletes.

## Session 2026-07-19 addendum — waves 2 + 3 landed

All of wave 2 and wave 3 shipped on `claude/session-progress-check-8pssi7` since the 2026-07-18 pause:

| Pass | Commit(s) | What landed |
|---|---|---|
| `clarify` | `00ade00` | Error UX + copy pass on `gateway/static/index.html` + `gateway/app.py`: deduped the tripled failure message, error-bearing progress steps settle with the fault icon (`level` field on emit), per-failure-class friendly one-liners with raw payload in a collapsed `<details>`, gateway-side `_friendly()` hostname sanitization (`api:3002`/`camoufox:3000`/`searxng:8888` → "scrape engine"/"browser engine"/"search engine") applied to emit messages, terminal/history errors, per-item error fields, and `/healthz`; killed the spurious PDF-path download step; empty-query submit now focuses + shows an inline hint; `/healthz` exposes `llm_configured` and the console disables/mutes the answer pills without a key; teaching hints for stealth, sitemap modes, crawl depth/pages/budget, and path-filter regex. |
| `audit` | `21ce0da` (merged via `06e9458`) | Accessibility + keyboard pass on `index.html`: real `<button>` disclosures with `aria-expanded` for `.ocollapse-head` and history rows (`.hexpand`); full WAI-ARIA tablist (`role="tablist"`/`tab`/`tabpanel`, `aria-selected`, roving `tabindex`, Left/Right/Home/End); `aria-label` on icon-only controls; single-line `aria-live="polite"` `#srStatus` region (phase changes + terminal outcome only); universal `:focus-visible` harvest-glow ring on every interactive element; `--ink-dim` recomputed from `#52655c` (2.6–2.97:1, failing AA) to `#798d82` (5.24:1 / 4.88:1 / 4.58:1 against bg/panel/panel-2 — computed, not guessed); `prefers-reduced-motion` block; `/` + `Cmd`/`Ctrl`+`Enter` keyboard accelerators with footer hint; rerun-from-history pill; per-panel `localStorage` persistence; fixed the History `rise` animation refiring on every tab revisit. |
| `polish` | `dda6ed7` | Integration residuals from the clarify+audit merge: history-detail timeline now renders `level==="error"` events with the fault icon/red instead of always green-check; `fillForm` (rerun-from-history) falls back to the "off" answer pill instead of restoring a disabled one when the LLM key isn't configured. |
| `document` (this pass) | _pending commit, see below_ | Regenerated `DESIGN.md` from the current `index.html` (five tabs, the full 14-value type ramp ratified by role, the off-palette color table, the `--ink-dim` contrast table, focus-glow/cancel-CTA/running-badge/confirm-pill/tablist/live-region documentation); refreshed `README.md` with a run-control / friendly-errors / accessibility / mobile section; refreshed this handoff file. |

**Remaining work — item 5 only:** re-run `/impeccable critique` against current `main`/this branch to score it against the 27/40 baseline. **Not runnable in this session** — the `impeccable` skill's critique step needs a live browser (Playwright) against a running gateway, and Docker is unavailable in this environment. Whoever resumes should rebuild and run the stack (`docker compose up -d --build gateway`, or `uvicorn app:app` per the cheatsheet below) and drive `/impeccable critique` from an environment with browser automation available.

**Verification caveat:** everything above is **code-verified only** — read against the actual `index.html`/`app.py`, cross-checked against the git log and diffs, contrast ratios independently recomputed. There has been **no live-stack verification** in this session (no Docker). The deploy note from the wave-1 entry still applies unchanged: `gateway/static/index.html` and `gateway/app.py` are baked into the gateway image at build time, so `docker compose up -d --build gateway` (not `restart`) is required to pick up any of this work once deployed.

## Git state at pause

- `main` = all completed work (see table). `impeccable/adapt` + `impeccable/harden` kept (merged); pushed to origin along with `main`.
- Wave-2 branches/worktrees produced **no commits** and were cleaned up (an empty `impeccable/clarify` branch pointing at pre-harden main was deleted; agent worktrees removed).
- `gateway/history.db` is runtime data — now gitignored.

## Verification cheatsheet for resuming

- Gateway from a worktree on a scratch port: `cd gateway && uvicorn app:app --port 809X` (read `app.py` for env names: `SEARXNG_URL`, `FIRECRAWL_URL`, browser URL, history DB path). Live upstreams: searxng :8888, firecrawl :3002, camoufox :3000.
- Deterministic design scan: `node ~/.claude/skills/impeccable/scripts/detect.mjs --json gateway/static/index.html`.
- Known pre-existing detector findings judged intentional (CRT aesthetic): dark-glow, scanline stripes, panel border+shadow, caps labels, Fraunces hits — see the critique's Anti-Patterns section before "fixing" them.
