# local-search

A fully self-hosted web search + page fetching pipeline for LLMs.

```
                        ┌──────────────────────────────────────────────┐
                        │                Docker Compose                │
  LLM / agent ──MCP──▶  │  gateway (FastAPI, :8088)                    │
  LLM / agent ──HTTP─▶  │    ├── /search ──▶ SearXNG (:8888)           │
                        │    │      └── answer ─▶ OpenRouter (LLM)     │
                        │    ├── /fetch ───▶ Firecrawl API (:3002)     │
                        │    │      └── PDFs parsed locally (pypdf)    │
                        │    ├── /crawl ───▶ Firecrawl crawl job       │
                        │    ├── /map ─────▶ Firecrawl map             │
                        │    ├── /history ─▶ SQLite run history        │
                        │    │                 ├── camoufox ◀─default  │
                        │    │                 ├── playwright-service  │
                        │    │                 ├── redis / rabbitmq    │
                        │    │                 └── nuq-postgres        │
                        │    └── screenshots ─▶ camoufox /screenshot   │
                        └──────────────────────────────────────────────┘
```

- **SearXNG** — self-hosted metasearch engine (aggregates Google, Bing, DuckDuckGo, …), JSON API enabled.
- **Firecrawl** (self-hosted, prebuilt GHCR images) — headless-browser scraping, returns clean markdown. Its native `SEARXNG_ENDPOINT` support is also wired up, so Firecrawl's own `/v2/search` works too.
- **Camoufox** (`camoufox/`) — [anti-detect Firefox](https://camoufox.com/) running Xvfb-backed virtual headless with spoofed fingerprints (presents as Windows desktop Firefox). It implements the same `/scrape` contract as Firecrawl's playwright-service and is wired in as **Firecrawl's default browser rendering engine**. It also exposes a `/screenshot` endpoint (full-page PNG via Playwright's `page.screenshot`) that the gateway calls **directly** — self-hosted Firecrawl cannot produce screenshots (that capability lives in its cloud-only fire-engine), so the `screenshot` format bypasses Firecrawl entirely.
- **Gateway** — a small FastAPI service exposing the LLM-friendly endpoints (search, fetch, crawl, map).
- **OpenRouter** (optional) — when an API key is configured, `/search` can synthesize a cited answer over the top results via any OpenAI-compatible chat endpoint (OpenRouter by default).
- **MCP server** — stdio MCP server (`mcp-server/`) exposing `web_search`, `fetch_page`, `crawl_site`, and `map_site` tools.

## Documentation

Full API reference, configuration options, and architecture notes: [`docs/index.html`](docs/index.html) — open in any browser.

## Start / stop

```bash
docker compose up -d      # first run pulls ~4GB of images
docker compose down       # stop
docker compose logs -f api   # watch firecrawl logs
```

Health check: `curl http://localhost:8088/healthz`

## Web console

Open **http://localhost:8088** in a browser for an interactive search and page-fetch console. The header shows live health status for all upstream services. Runs show a live step-by-step progress log ("querying searxng… → scraping … → rendering screenshot…") as they execute, and the **History** tab lists past runs with their full event timelines.

Every output format renders in its own tabbed panel with one-click **copy to clipboard** and **file download** (`.md`, `.html`, `.txt`, `.json`, `.png`). Markdown shows the raw text by default with a rendered-preview toggle; the screenshot copy button places the actual PNG on the clipboard.

## Progress events & run history

Every run (search or fetch, including MCP-driven ones) emits timestamped progress events. They go three places:

1. **Server logs** — `docker compose logs -f gateway` shows each step (`scrape: scraping … via firecrawl`, `screenshot: captured … (1878 KB png)`); `docker compose logs -f camoufox` shows per-page render timing and full tracebacks on failure.
2. **SSE streaming endpoints** — `POST /search/stream` and `POST /fetch/stream` accept the same JSON bodies as their non-stream counterparts but respond with `text/event-stream`: a series of `{"type":"event","t_ms":…,"stage":…,"message":…}` lines followed by a final `{"type":"result","data":…}` (or `{"type":"error","error":…}`). The web console uses these.
3. **Run history (SQLite)** — every run is recorded to a local SQLite DB (`HISTORY_DB`, default `/data/history.db`, persisted in the `gateway-data` volume):
   - `GET /history?limit=50&offset=0` — recent runs (kind, label, status, duration, summary)
   - `GET /history/{id}` — one run with its full event timeline and original request
   - `DELETE /history/{id}` / `DELETE /history` — delete one run / clear all

```bash
# Watch a fetch execute step-by-step
curl -sN -X POST http://localhost:8088/fetch/stream \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "formats": ["markdown","screenshot"]}'

# What ran recently, and how long did it take?
curl -s 'http://localhost:8088/history?limit=10'
```

## HTTP API (for any LLM tool-calling setup)

### Search

```bash
# Simple search
curl 'http://localhost:8088/search?q=rust+async+runtime+comparison&max_results=5'

# Search AND scrape the top 3 results into markdown (one call)
curl -X POST http://localhost:8088/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "rust async runtime comparison", "max_results": 8, "fetch_content": true, "fetch_top": 3}'
```

Optional params: `categories` (general/news/it/science/…), `language`, `time_range` (day/week/month/year), `engines` (comma-separated allowlist like `google,bing`), `pageno` (1-based pagination), `safesearch` (0 off / 1 mod / 2 strict).

**Domain & date filters:**
- `include_domains` / `exclude_domains` — arrays (max 10 each) of domains; matching is host-suffix aware, so `docs.python.org` matches subdomains too. When filters are active the gateway overfetches up to 3 SearXNG pages to still fill `max_results`, and rewrites the query with `site:` / `-site:` operators as a recall hint (the gateway-side filter is authoritative regardless).
- `start_date` / `end_date` — `YYYY-MM-DD`; results published outside the window are dropped. **Undated results are kept** — SearXNG omits publication dates for most results, so filtering them out would empty result sets.

```bash
# Only results from these two domains
curl -X POST http://localhost:8088/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "asyncio tutorial", "include_domains": ["docs.python.org","realpython.com"]}'
```

**Synthesized answer (`include_answer`):** `false` (default), `true`/`"basic"` (answer from titles+snippets), or `"advanced"` (also feed scraped page content — pair with `fetch_content: true` and a `markdown` format, otherwise it falls back to snippets). Requires `OPENROUTER_API_KEY` on the gateway (see [Answer synthesis](#answer-synthesis-openrouter)); returns an `answer` (with inline `[n]` citations) and `answer_model` field. Answer synthesis is best-effort — if the key is missing or the call fails, the search still succeeds and an `answer_error` field explains why.

When `fetch_content: true`, you also control **what** gets scraped per result:
- `fetch_formats` — array of `markdown` (default), `html`, `rawHtml`, `links`, `json`, `screenshot`
- `fetch_stealth` — route enriched scrapes through the Camoufox anti-detect browser

```bash
# Enrich results with markdown + outbound links, using stealth rendering
curl -X POST http://localhost:8088/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "cloudflare turnstile bypass research", "fetch_content": true,
       "fetch_formats": ["markdown","links"], "fetch_stealth": true}'

# Search + cited answer over the top results
curl -X POST http://localhost:8088/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "what is searxng", "include_answer": true}'
```

### Fetch a page (or a batch)

```bash
# Single URL
curl -X POST http://localhost:8088/fetch \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://docs.firecrawl.dev", "max_chars": 20000}'

# Batch: up to 20 URLs, fetched concurrently
curl -X POST http://localhost:8088/fetch \
  -H 'Content-Type: application/json' \
  -d '{"urls": ["https://example.com","https://docs.firecrawl.dev"], "formats": ["markdown"]}'
```

Provide **exactly one** of `url` or `urls` (both/neither → 422). A single fetch returns `{url, title, description, status_code, language, formats, markdown, ...}` plus whichever additional formats were requested. A batch returns `{urls, result_count, failed_count, results: [...], failed_results: [{url, error}]}` — each result has the same shape as a single fetch, and per-URL failures are isolated so partial batches still return.

**PDFs:** URLs that serve a PDF (detected by `.pdf` extension, and otherwise by content sniffing when Firecrawl returns empty/errors) are downloaded and parsed locally with `pypdf` — self-hosted Firecrawl can't parse PDFs itself. The response carries `is_pdf: true` and `page_count`, with `markdown` laid out as `## Page N` sections (and `json` structure derived from it). Screenshots aren't supported for PDFs (returns `screenshot_error`); scanned/image PDFs with no text layer return a note. Downloads are capped at 20 MB.

**Formats** (`formats`, default `["markdown"]`):

| format       | field returned  | notes |
|--------------|-----------------|-------|
| `markdown`   | `markdown`      | clean extracted text (default) |
| `html`       | `html`          | cleaned HTML (respects `only_main_content`) |
| `rawHtml`    | `raw_html`      | unmodified page HTML |
| `links`      | `links`         | array of outbound URLs |
| `json`       | `json`          | the scraped markdown decomposed server-side into a nested section tree keyed by heading hierarchy: `{title, url, sections: [{heading, level, text, list, links, images, code, sections}]}` (empty fields omitted). Derived from markdown — no extra fetch |
| `screenshot` | `screenshot`    | full-page base64 PNG, captured by camoufox directly (not Firecrawl) — large, request only when needed. When combined with other formats the page is fetched twice (Firecrawl for text, camoufox for the image); on capture failure the other formats still return, with a `screenshot_error` field. If the full-page capture fails (very tall pages, memory pressure) camoufox falls back to a viewport-only shot and sets `screenshot_note` |

**Content-shaping options:**

| option             | type           | what it does |
|--------------------|----------------|--------------|
| `only_main_content`| bool (true)    | strip nav/footer boilerplate (markdown & html) |
| `include_tags`     | list[str]      | CSS selectors to keep, e.g. `["article","main"]` |
| `exclude_tags`     | list[str]      | CSS selectors to drop, e.g. `["nav","footer",".ads"]` |
| `max_chars`        | int            | truncate returned markdown (sets `truncated: true`) |
| `max_tokens`       | int            | LLM-token budget for returned markdown |
| `wait_for`         | int (ms)       | wait before extracting (let JS render) |
| `timeout`          | int (ms)       | override scrape timeout |
| `location`         | str            | ISO-3166 country code to geo-route from (`US`, `GB`, …) |
| `actions`          | list[object]   | pre-extract interactions (wait/click/scroll/screenshot/write/press) |
| `stealth`          | bool           | force Camoufox anti-detect browser (slower; for bot-protected sites) |

```bash
# Markdown + screenshot of a JS-heavy page, rendered stealthily from the US
curl -X POST http://localhost:8088/fetch \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://some-protected-site.com",
       "formats": ["markdown","screenshot"], "stealth": true, "location": "US",
       "wait_for": 1500, "exclude_tags": ["nav",".cookie-banner"]}'
```

For bot-protected sites, add `"stealth": true` — this forces rendering through the Camoufox anti-detect browser instead of a plain HTTP fetch (slower but much harder to block):

```bash
curl -X POST http://localhost:8088/fetch \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://some-protected-site.com", "stealth": true}'
```

### Crawl a site

`POST /crawl` follows links from a root URL and returns the content of every crawled page. The gateway drives Firecrawl's async crawl job to completion internally (polling and emitting progress), so a single request returns all pages — use `/crawl/stream` to watch `N/M pages` ticks live.

```bash
curl -X POST http://localhost:8088/crawl \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://docs.firecrawl.dev", "limit": 25,
       "include_paths": ["/features/.*"], "formats": ["markdown","json"]}'
```

| option | type | default | notes |
|--------|------|---------|-------|
| `url` | str | — | root URL |
| `limit` | int | 25 | max pages (**hard cap 100**) |
| `max_depth` | int | — | max discovery depth from the root |
| `include_paths` / `exclude_paths` | list[str] | — | regex patterns of URL paths |
| `crawl_entire_domain` | bool | false | follow sibling/parent URLs, not just children |
| `allow_subdomains` / `allow_external_links` | bool | false | widen crawl scope |
| `sitemap` | str | `include` | `include` / `skip` / `only` |
| `delay` | float | — | seconds between page scrapes |
| `formats` | list[str] | `["markdown"]` | per-page: markdown/html/rawHtml/links/json (**no screenshot**) |
| `only_main_content` | bool | true | strip nav/footer boilerplate |
| `max_chars` | int | — | per-page markdown truncation |
| `timeout_s` | int | 300 | overall crawl budget (30–900); on timeout the job is cancelled and partial pages returned |

Returns `{url, job_id, status: completed|timeout|failed, partial, total, page_count, formats, pages: [...]}`. Each page has the same shape as a single fetch. Timeout/failure with partial pages returns HTTP 200 with `status`/`partial` markers (not an error), so you keep whatever was crawled.

### Map a site

`POST /map` discovers a site's URLs (sitemap + link discovery) without scraping page content — fast, and useful for scoping a crawl.

```bash
curl -X POST http://localhost:8088/map \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://docs.firecrawl.dev", "search": "crawl", "limit": 100}'
```

Params: `url`, `search` (filter/rank links by term), `limit` (default 100, max 5000), `include_subdomains` (default true), `sitemap` (`include`/`skip`/`only`). Returns `{url, link_count, links: [{url, title?, description?}]}`.

## MCP server

Tools:
- `web_search(query, max_results, fetch_content, fetch_top, fetch_formats, fetch_stealth, categories, language, engines, pageno, safesearch, time_range, include_domains, exclude_domains, start_date, end_date, include_answer)`
- `fetch_page(url | urls, formats, only_main_content, include_tags, exclude_tags, max_chars, max_tokens, wait_for, timeout, location, actions, stealth)` — one URL or a batch of up to 20; PDFs parsed locally
- `crawl_site(url, limit, max_depth, include_paths, exclude_paths, crawl_entire_domain, allow_subdomains, formats, max_chars, timeout_s)`
- `map_site(url, search, limit, include_subdomains, sitemap)`

Register with Claude Code:

```bash
claude mcp add local-search -- node /Users/coleparsons/Desktop/local-search/mcp-server/index.js
```

Or in any MCP client config:

```json
{
  "mcpServers": {
    "local-search": {
      "command": "node",
      "args": ["/Users/coleparsons/Desktop/local-search/mcp-server/index.js"],
      "env": { "GATEWAY_URL": "http://localhost:8088" }
    }
  }
}
```

## Answer synthesis (OpenRouter)

`/search`'s `include_answer` calls an OpenAI-compatible chat endpoint (OpenRouter by default) to synthesize a cited answer over the top results. Configure it with a local `.env` file (see `.env.example`; `.env` is gitignored):

```bash
OPENROUTER_API_KEY=sk-or-...           # required to enable answers
ANSWER_MODEL=openai/gpt-4o-mini        # any model slug your endpoint accepts
ANSWER_BASE_URL=https://openrouter.ai/api/v1   # override for Ollama/vLLM/etc.
```

`docker compose up -d gateway` picks these up (they're passed through in `docker-compose.yml`). Point `ANSWER_BASE_URL` at any OpenAI-compatible `/chat/completions` server to keep answers fully self-hosted. Without a key, search still works — only the answer is skipped (with an `answer_error`).

## Direct upstream access (optional)

- SearXNG UI/API: `http://localhost:8888` (`/search?q=...&format=json`)
- Firecrawl API: `http://localhost:3002` (`POST /v2/scrape`, `POST /v2/search`, `POST /v2/crawl`) — no API key needed (auth disabled for self-host); pass any `Authorization: Bearer x` if a client requires one.

## Notes

- SearXNG's `settings.yml` enables the JSON output format (required for the API) and disables the bot limiter — keep this instance private / on localhost.
- Engines can be tuned in `searxng/settings.yml` (see SearXNG docs); by default the standard engine set is active.
- Firecrawl resource limits (`cpus`, `mem_limit` on `api` / `playwright-service` / `camoufox`) can be raised in `docker-compose.yml` for heavier crawling.
- Camoufox is Firecrawl's browser engine by default (`PLAYWRIGHT_MICROSERVICE_URL` points at it). To switch back to stock Playwright/Chromium: `PLAYWRIGHT_MICROSERVICE_URL=http://playwright-service:3000/scrape docker compose up -d api` (or put it in a `.env` file).
- Note: even without `stealth: true`, Firecrawl only escalates to the browser engine when its plain HTTP fetch isn't sufficient; `stealth: true` forces browser rendering every time.
- `/crawl` is capped at 100 pages per request (`limit`) and bounded by `timeout_s` (default 300s); it's a synchronous facade over Firecrawl's async crawl job — for very large crawls, split by `include_paths` or call Firecrawl's `/v2/crawl` directly.

## Hardening bot-detection evasion

Known gaps in the current anti-detect stack (review the `camoufox/server.py` and `gateway/app.py` against this list before relying on it for hardened targets):

**Camoufox engine (`camoufox/server.py`)**
- A single shared browser context is reused for every request — cookies/storage leak across requests and every page shares one fingerprint. Open a fresh `BrowserContext` per request and close it after.
- `humanize=True` (human-like cursor/typing) and `geoip=True` (locale/timezone match the egress IP — the `geoip` extra is already installed in the Dockerfile) are **not** enabled. Both are free wins.
- No proxy support. Wire `CAMOUFOX_PROXY` / `proxy={server,user,password}` so IP reputation can be rotated — the single biggest lever against bot detection.
- No human-like timing. `wait_after_load` defaults to `0`; add randomized dwell, a short scroll, and mouse jitter before `page.content()`.
- Header forwarding only drops `user-agent`; `sec-ch-ua`, `accept-language`, `sec-fetch-*`, `cookie` from the caller can still clash with the spoofed fingerprint — let Camoufox own all client-hint headers.
- No block detection / fresh-context retry on 403/429/503 or challenge-page text (`"Just a moment"`, `cf-challenge`).
- No warm-up navigation and no per-context OS/locale rotation, so every request presents the same Windows/Firefox fingerprint — a correlation anchor.

**Gateway (`gateway/app.py`)**
- `stealth` forces the browser engine via the `waitFor: 500` hint, which Firecrawl treats as advisory, not guaranteed. For hard guarantees, POST directly to the camoufox `/scrape` endpoint or pass a real Firecrawl engine flag.
- No retry/backoff with fingerprint refresh on 4xx/5xx.
- The global 90s `httpx` timeout covers both stealth and non-stealth; non-stealth paths should time out faster.

**Search side (`searxng/settings.yml`)**
- SearXNG's own outgoing requests get blocked by Google/Bing on datacenter IPs. `outgoing.proxies` and UA rotation are unconfigured — this is the search-side bot-detection surface and currently unaddressed.

**Infrastructure**
- The highest-leverage change is a residential/rotating-proxy egress shared by camoufox and SearXNG. A Cloudflare-challenge solver (e.g. flaresolverr) as a fallback is worth adding for Cloudflare-fronted targets.
