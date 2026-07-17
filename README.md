# local-search

A fully self-hosted web search + page fetching pipeline for LLMs.

```
                        ┌──────────────────────────────────────────────┐
                        │                Docker Compose                │
  LLM / agent ──MCP──▶  │  gateway (FastAPI, :8088)                    │
  LLM / agent ──HTTP─▶  │    ├── /search ──▶ SearXNG (:8888)           │
                        │    └── /fetch ───▶ Firecrawl API (:3002)     │
                        │                      ├── camoufox ◀─default  │
                        │                      ├── playwright-service  │
                        │                      ├── redis / rabbitmq    │
                        │                      └── nuq-postgres        │
                        └──────────────────────────────────────────────┘
```

- **SearXNG** — self-hosted metasearch engine (aggregates Google, Bing, DuckDuckGo, …), JSON API enabled.
- **Firecrawl** (self-hosted, prebuilt GHCR images) — headless-browser scraping, returns clean markdown. Its native `SEARXNG_ENDPOINT` support is also wired up, so Firecrawl's own `/v2/search` works too.
- **Camoufox** (`camoufox/`) — [anti-detect Firefox](https://camoufox.com/) running Xvfb-backed virtual headless with spoofed fingerprints (presents as Windows desktop Firefox). It implements the same `/scrape` contract as Firecrawl's playwright-service and is wired in as **Firecrawl's default browser rendering engine**.
- **Gateway** — a small FastAPI service exposing the two LLM-friendly endpoints.
- **MCP server** — stdio MCP server (`mcp-server/`) exposing `web_search` and `fetch_page` tools.

## Start / stop

```bash
docker compose up -d      # first run pulls ~4GB of images
docker compose down       # stop
docker compose logs -f api   # watch firecrawl logs
```

Health check: `curl http://localhost:8088/healthz`

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

Optional params: `categories` (general/news/it/science/…), `language`, `time_range` (day/week/month/year).

### Fetch a page

```bash
curl -X POST http://localhost:8088/fetch \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://docs.firecrawl.dev", "max_chars": 20000}'
```

Returns `{url, title, description, markdown, status_code}`.

For bot-protected sites, add `"stealth": true` — this forces rendering through the Camoufox anti-detect browser instead of a plain HTTP fetch (slower but much harder to block):

```bash
curl -X POST http://localhost:8088/fetch \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://some-protected-site.com", "stealth": true}'
```

## MCP server

Tools: `web_search(query, max_results, fetch_content, fetch_top, time_range)` and `fetch_page(url, only_main_content, max_chars, stealth)`.

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

## Direct upstream access (optional)

- SearXNG UI/API: `http://localhost:8888` (`/search?q=...&format=json`)
- Firecrawl API: `http://localhost:3002` (`POST /v2/scrape`, `POST /v2/search`, `POST /v2/crawl`) — no API key needed (auth disabled for self-host); pass any `Authorization: Bearer x` if a client requires one.

## Notes

- SearXNG's `settings.yml` enables the JSON output format (required for the API) and disables the bot limiter — keep this instance private / on localhost.
- Engines can be tuned in `searxng/settings.yml` (see SearXNG docs); by default the standard engine set is active.
- Firecrawl resource limits (`cpus`, `mem_limit` on `api` / `playwright-service` / `camoufox`) can be raised in `docker-compose.yml` for heavier crawling.
- Camoufox is Firecrawl's browser engine by default (`PLAYWRIGHT_MICROSERVICE_URL` points at it). To switch back to stock Playwright/Chromium: `PLAYWRIGHT_MICROSERVICE_URL=http://playwright-service:3000/scrape docker compose up -d api` (or put it in a `.env` file).
- Note: even without `stealth: true`, Firecrawl only escalates to the browser engine when its plain HTTP fetch isn't sufficient; `stealth: true` forces browser rendering every time.
