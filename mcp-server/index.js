#!/usr/bin/env node
// MCP server for the local-search pipeline (SearXNG + Firecrawl behind the gateway API).
// Tools: web_search (search the web, optional cited answer), fetch_page (one URL or a
// batch of up to 20, PDFs included), crawl_site (multi-page crawl), map_site (URL discovery).

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const GATEWAY_URL = (process.env.GATEWAY_URL || "http://localhost:8088").replace(/\/$/, "");

const server = new McpServer({
  name: "local-search",
  version: "1.0.0",
});

async function callGateway(path, body, timeoutMs = 120_000) {
  const res = await fetch(`${GATEWAY_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Gateway ${path} returned ${res.status}: ${text.slice(0, 500)}`);
  }
  return res.json();
}

const FORMAT_ENUMS = ["markdown", "html", "rawHtml", "links", "json", "screenshot"];

server.registerTool(
  "web_search",
  {
    title: "Web search",
    description:
      "Search the web (self-hosted SearXNG metasearch: Google, Bing, DuckDuckGo, etc). " +
      "Returns titles, URLs, and snippets. Set fetch_content=true to also scrape the top " +
      "results and include their full page content in the requested fetch_formats.",
    inputSchema: {
      query: z.string().describe("Search query, like you would type into Google"),
      max_results: z.number().int().min(1).max(30).default(8).describe("Max results to return"),
      fetch_content: z
        .boolean()
        .default(false)
        .describe("Also scrape top results and include full page content (slower)"),
      fetch_top: z
        .number()
        .int()
        .min(1)
        .max(10)
        .default(3)
        .describe("How many top results to scrape when fetch_content is true"),
      fetch_formats: z
        .array(z.enum(FORMAT_ENUMS))
        .default(["markdown"])
        .describe(
          "Formats to scrape for each enriched result when fetch_content=true. " +
            "Options: markdown, html, rawHtml, links, json (markdown decomposed into " +
            "nested sections), screenshot"
        ),
      fetch_stealth: z
        .boolean()
        .default(false)
        .describe("Use the Camoufox anti-detect browser when enriching results (slower, harder to block)"),
      categories: z
        .string()
        .default("general")
        .describe("SearXNG category, e.g. 'general', 'news', 'it', 'science'"),
      language: z.string().default("en").describe("Search language code, e.g. 'en', 'de', 'ja'"),
      engines: z
        .string()
        .optional()
        .describe("Comma-separated SearXNG engine allowlist, e.g. 'google,bing,duckduckgo'"),
      pageno: z.number().int().min(1).default(1).describe("Result page number (1-based)"),
      safesearch: z
        .number()
        .int()
        .min(-1)
        .max(2)
        .default(0)
        .describe("Safe search level: 0 off, 1 moderate, 2 strict"),
      time_range: z
        .enum(["day", "week", "month", "year"])
        .optional()
        .describe("Restrict results to a recent time window"),
      include_domains: z
        .array(z.string())
        .max(10)
        .optional()
        .describe("Only return results from these domains (subdomains match too)"),
      exclude_domains: z
        .array(z.string())
        .max(10)
        .optional()
        .describe("Drop results from these domains"),
      start_date: z
        .string()
        .optional()
        .describe("YYYY-MM-DD; drop results published before this (undated results kept)"),
      end_date: z
        .string()
        .optional()
        .describe("YYYY-MM-DD; drop results published after this (undated results kept)"),
      include_answer: z
        .union([z.boolean(), z.enum(["basic", "advanced"])])
        .default(false)
        .describe(
          "Synthesize a cited answer from top results via LLM (needs OPENROUTER_API_KEY " +
            "on the gateway). 'advanced' also uses scraped content when fetch_content=true"
        ),
    },
  },
  async ({
    query,
    max_results,
    fetch_content,
    fetch_top,
    fetch_formats,
    fetch_stealth,
    categories,
    language,
    engines,
    pageno,
    safesearch,
    time_range,
    include_domains,
    exclude_domains,
    start_date,
    end_date,
    include_answer,
  }) => {
    const data = await callGateway("/search", {
      query,
      max_results,
      fetch_content,
      fetch_top,
      fetch_formats,
      fetch_stealth,
      categories,
      language,
      engines: engines ?? null,
      pageno,
      safesearch,
      time_range: time_range ?? null,
      include_domains: include_domains ?? null,
      exclude_domains: exclude_domains ?? null,
      start_date: start_date ?? null,
      end_date: end_date ?? null,
      include_answer,
    });
    return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
  }
);

server.registerTool(
  "fetch_page",
  {
    title: "Fetch page",
    description:
      "Fetch one web page (url) or a batch of up to 20 (urls) via self-hosted Firecrawl " +
      "(headless browser) and return content in the requested formats (markdown by default). " +
      "PDF URLs are parsed locally into per-page markdown. For bot-protected sites set " +
      "stealth=true to force the Camoufox anti-detect browser.",
    inputSchema: {
      url: z.string().url().optional().describe("The URL to fetch (exactly one of url/urls)"),
      urls: z
        .array(z.string().url())
        .min(1)
        .max(20)
        .optional()
        .describe("Batch: up to 20 URLs fetched concurrently (exactly one of url/urls)"),
      formats: z
        .array(z.enum(FORMAT_ENUMS))
        .default(["markdown"])
        .describe(
          "Output formats to return. markdown = clean text; html = cleaned HTML; " +
            "rawHtml = unmodified page HTML; links = outbound link list; " +
            "json = markdown decomposed into nested sections (heading/text/list/links/images); " +
            "screenshot = base64-encoded PNG (large — request only when needed)"
        ),
      only_main_content: z
        .boolean()
        .default(true)
        .describe("Strip navigation/footer boilerplate (applies to markdown & html)"),
      include_tags: z
        .array(z.string())
        .optional()
        .describe("CSS selectors/tags to include, e.g. ['article', 'main']"),
      exclude_tags: z
        .array(z.string())
        .optional()
        .describe("CSS selectors/tags to exclude, e.g. ['nav', 'footer', '.ads']"),
      max_chars: z
        .number()
        .int()
        .min(1000)
        .optional()
        .describe("Optionally truncate the returned markdown to this many characters"),
      max_tokens: z
        .number()
        .int()
        .positive()
        .optional()
        .describe("Optional LLM-token budget for the returned markdown"),
      wait_for: z
        .number()
        .int()
        .nonnegative()
        .optional()
        .describe("ms to wait on the page before extracting content (let JS render)"),
      timeout: z
        .number()
        .int()
        .positive()
        .optional()
        .describe("Override scrape timeout in ms"),
      location: z
        .string()
        .optional()
        .describe("ISO-3166 country code to geo-route from, e.g. 'US', 'GB'"),
      actions: z
        .array(z.record(z.string(), z.unknown()))
        .optional()
        .describe(
          "Pre-extract interactions: [{type:'wait'|'click'|'scroll'|'screenshot'|'write'|'press', " +
            "selector?, text?, key?, ...}]. Useful for bot-protected sites that need interaction."
        ),
      stealth: z
        .boolean()
        .default(false)
        .describe(
          "Force rendering through the Camoufox anti-detect browser. Slower; " +
            "use when a normal fetch is blocked (Cloudflare, bot walls, etc)."
        ),
    },
  },
  async ({
    url,
    urls,
    formats,
    only_main_content,
    include_tags,
    exclude_tags,
    max_chars,
    max_tokens,
    wait_for,
    timeout,
    location,
    actions,
    stealth,
  }) => {
    if (Boolean(url) === Boolean(urls)) {
      throw new Error("Provide exactly one of 'url' or 'urls'");
    }
    const data = await callGateway(
      "/fetch",
      {
        url: url ?? null,
        urls: urls ?? null,
        formats,
        only_main_content,
        include_tags: include_tags ?? null,
        exclude_tags: exclude_tags ?? null,
        max_chars: max_chars ?? null,
        max_tokens: max_tokens ?? null,
        wait_for: wait_for ?? null,
        timeout: timeout ?? null,
        location: location ?? null,
        actions: actions ?? null,
        stealth,
      },
      urls ? 300_000 : 120_000
    );
    return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
  }
);

const CRAWL_FORMAT_ENUMS = ["markdown", "html", "rawHtml", "links", "json"];

server.registerTool(
  "crawl_site",
  {
    title: "Crawl site",
    description:
      "Crawl a website via self-hosted Firecrawl: follow links from a root URL and return " +
      "the content of every crawled page. Slow (can take minutes) and returns many pages — " +
      "keep limit small and use include_paths to focus. For a lightweight URL inventory " +
      "without scraping, use map_site instead.",
    inputSchema: {
      url: z.string().url().describe("Root URL to crawl from"),
      limit: z.number().int().min(1).max(100).default(25).describe("Max pages (hard cap 100)"),
      max_depth: z
        .number()
        .int()
        .min(0)
        .optional()
        .describe("Max discovery depth from the root URL"),
      include_paths: z
        .array(z.string())
        .optional()
        .describe("Regex patterns of URL paths to crawl, e.g. ['/blog/.*']"),
      exclude_paths: z
        .array(z.string())
        .optional()
        .describe("Regex patterns of URL paths to skip"),
      crawl_entire_domain: z
        .boolean()
        .default(false)
        .describe("Follow sibling/parent URLs, not just child paths of the root"),
      allow_subdomains: z.boolean().default(false).describe("Follow links onto subdomains"),
      formats: z
        .array(z.enum(CRAWL_FORMAT_ENUMS))
        .default(["markdown"])
        .describe("Per-page output formats (screenshots not supported for crawls)"),
      max_chars: z
        .number()
        .int()
        .min(1000)
        .optional()
        .describe("Per-page markdown truncation"),
      timeout_s: z
        .number()
        .int()
        .min(30)
        .max(900)
        .default(300)
        .describe("Overall crawl budget in seconds; partial pages are returned on timeout"),
    },
  },
  async ({ timeout_s, ...rest }) => {
    const data = await callGateway(
      "/crawl",
      { ...rest, timeout_s },
      (timeout_s ?? 300) * 1000 + 30_000
    );
    return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
  }
);

server.registerTool(
  "map_site",
  {
    title: "Map site",
    description:
      "Discover a website's URLs via self-hosted Firecrawl (sitemap + link discovery) " +
      "without scraping page content. Fast; use before crawl_site to scope a crawl.",
    inputSchema: {
      url: z.string().url().describe("Site to map"),
      search: z
        .string()
        .optional()
        .describe("Filter/rank discovered links by this term, e.g. 'blog'"),
      limit: z.number().int().min(1).max(5000).default(100).describe("Max URLs to return"),
      include_subdomains: z.boolean().default(true).describe("Include links on subdomains"),
      sitemap: z
        .enum(["include", "skip", "only"])
        .default("include")
        .describe("Sitemap usage: combine with discovery (include), ignore it, or use it alone"),
    },
  },
  async (args) => {
    const data = await callGateway("/map", { ...args, search: args.search ?? null });
    return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
  }
);

const transport = new StdioServerTransport();
await server.connect(transport);
console.error(
  `local-search MCP server running (gateway: ${GATEWAY_URL}; tools: web_search, fetch_page, crawl_site, map_site)`
);
