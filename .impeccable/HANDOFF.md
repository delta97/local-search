# Impeccable critique → fix campaign: handoff

_Last updated: 2026-07-18. Session paused mid-campaign; this documents exactly where things stand so it can be finished later._

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

## ⏳ Not done (wave 2 + 3 — agents were launched then interrupted before writing any code)

Run these against current `main`. Critique line numbers are stale; read current code. Both wave-2 tasks are `index.html`-focused and were designed to run in parallel worktrees with a scope firewall:

1. **`/impeccable clarify`** (Opus) — error UX + copy. Scope: dedupe the tripled failure message; error-bearing progress events must settle with the fault icon, never the green check; per-failure-class one-line human summaries ("couldn't scrape this site — try stealth") with raw payload in a collapsed `<details>`; sanitize internal hostnames (`api:3002`, `camoufox:3000`) at the gateway (don't break MCP response shapes) and in the header health readout (friendly service names); kill the spurious "downloading (pdf path)" step after a fatal fetch error; empty-query submit → focus + inline hint (currently silent no-op); disable "answer" pills when no LLM key is configured (expose via `/healthz`); teaching copy for stealth / sitemap include-skip-only / depth vs pages vs budget / regex path filters (existing hint vocabulary, no tooltips framework, no modals). Firewall: don't touch aria-*, focus styles, tab semantics, `--ink-dim`, keyboard handlers, CSS media queries.
2. **`/impeccable audit`** (Opus) — keyboard/AT/contrast + Alex's accelerators. Scope: `.ocollapse-head` disclosures + `.hrun` cards → real buttons w/ `aria-expanded`; WAI-ARIA tablist pattern w/ arrow keys; `aria-label` on icon-only buttons; verify harden's new controls are keyboard-operable; `aria-live="polite"` status announcement (avoid SR spam — single updating status line beats the whole log); global `:focus-visible` harvest glow on ALL interactive elements; bump `--ink-dim` (#52655c, measures 2.77–2.97:1) to ≥4.5:1 against forest-void/panel/card (compute, don't guess; keep distinct from `--ink-muted`); `prefers-reduced-motion` block; `/` focuses active panel input, ⌘/Ctrl+Enter submits, footer hint; **rerun-from-history** pill (load recorded request params back into the form — see how harden's attach reads them); persist per-panel options to localStorage; fix History `rise` animation refiring on every tab visit. Firewall: `index.html` only, no error strings/health-readout copy, no `app.py`.
3. **`/impeccable polish`** (Fable, after 1+2 merge) — final pass on merged main with live browser verification (rebuild gateway first). Fix residuals; visually confirm mobile on the real running app (adapt's device-level check is still owed).
4. **`/impeccable document`** (Sonnet, last) — regenerate `DESIGN.md` from final code: five tabs not three, real type ramp (the 18 off-ramp literals: 10/12/12.5/13/13.5/14px — ratify or correct), off-palette colors (`#ffca5c`, `#b9c7bf`, `rgba(0,0,0,.12)`), new ink-dim value from audit, focus-glow behavior as implemented, plus harden's new components (cancel CTA, running badges, confirm pills).
5. Re-run **`/impeccable critique`** to measure the score against the 27/40 baseline (trend is tracked per-slug in `.impeccable/critique/`).

Smaller leftovers folded into the passes above: history URLs set in Fraunces serif (Domain Rule artifact), answer-pill dead end, `aria-label` on deletes.

## Git state at pause

- `main` = all completed work (see table). `impeccable/adapt` + `impeccable/harden` kept (merged); pushed to origin along with `main`.
- Wave-2 branches/worktrees produced **no commits** and were cleaned up (an empty `impeccable/clarify` branch pointing at pre-harden main was deleted; agent worktrees removed).
- `gateway/history.db` is runtime data — now gitignored.

## Verification cheatsheet for resuming

- Gateway from a worktree on a scratch port: `cd gateway && uvicorn app:app --port 809X` (read `app.py` for env names: `SEARXNG_URL`, `FIRECRAWL_URL`, browser URL, history DB path). Live upstreams: searxng :8888, firecrawl :3002, camoufox :3000.
- Deterministic design scan: `node ~/.claude/skills/impeccable/scripts/detect.mjs --json gateway/static/index.html`.
- Known pre-existing detector findings judged intentional (CRT aesthetic): dark-glow, scanline stripes, panel border+shadow, caps labels, Fraunces hits — see the critique's Anti-Patterns section before "fixing" them.
