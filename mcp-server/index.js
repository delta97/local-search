#!/usr/bin/env node
// MCP server for the local-search pipeline (SearXNG + Firecrawl behind the gateway API).
// Tools: web_search (search the web), fetch_page (get a page as markdown).

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const GATEWAY_URL = (process.env.GATEWAY_URL || "http://localhost:8088").replace(/\/$/, "");

const server = new McpServer({
  name: "local-search",
  version: "1.0.0",
});

async function callGateway(path, body) {
  const res = await fetch(`${GATEWAY_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(120_000),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Gateway ${path} returned ${res.status}: ${text.slice(0, 500)}`);
  }
  return res.json();
}

const FORMAT_ENUMS = ["markdown", "html", "rawHtml", "links", "screenshot"];

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
            "Options: markdown, html, rawHtml, links, screenshot"
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
    });
    return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
  }
);

server.registerTool(
  "fetch_page",
  {
    title: "Fetch page",
    description:
      "Fetch a single web page via self-hosted Firecrawl (headless browser) and return its " +
      "content in the requested formats (markdown by default). Use for reading a specific URL. " +
      "For bot-protected sites set stealth=true to force the Camoufox anti-detect browser.",
    inputSchema: {
      url: z.string().url().describe("The URL to fetch"),
      formats: z
        .array(z.enum(FORMAT_ENUMS))
        .default(["markdown"])
        .describe(
          "Output formats to return. markdown = clean text; html = cleaned HTML; " +
            "rawHtml = unmodified page HTML; links = outbound link list; " +
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
    const data = await callGateway("/fetch", {
      url,
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
    });
    return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
  }
);

const transport = new StdioServerTransport();
await server.connect(transport);
console.error(`local-search MCP server running (gateway: ${GATEWAY_URL})`);
