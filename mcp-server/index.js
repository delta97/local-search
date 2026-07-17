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

server.registerTool(
  "web_search",
  {
    title: "Web search",
    description:
      "Search the web (self-hosted SearXNG metasearch: Google, Bing, DuckDuckGo, etc). " +
      "Returns titles, URLs, and snippets. Set fetch_content=true to also scrape the top " +
      "results and include their full page content as markdown.",
    inputSchema: {
      query: z.string().describe("Search query, like you would type into Google"),
      max_results: z.number().int().min(1).max(30).default(8).describe("Max results to return"),
      fetch_content: z
        .boolean()
        .default(false)
        .describe("Also scrape top results and include full page markdown (slower)"),
      fetch_top: z
        .number()
        .int()
        .min(1)
        .max(10)
        .default(3)
        .describe("How many top results to scrape when fetch_content is true"),
      time_range: z
        .enum(["day", "week", "month", "year"])
        .optional()
        .describe("Restrict results to a recent time window"),
    },
  },
  async ({ query, max_results, fetch_content, fetch_top, time_range }) => {
    const data = await callGateway("/search", {
      query,
      max_results,
      fetch_content,
      fetch_top,
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
      "content as clean markdown. Use for reading a specific URL in full.",
    inputSchema: {
      url: z.string().url().describe("The URL to fetch"),
      only_main_content: z
        .boolean()
        .default(true)
        .describe("Strip navigation/footer boilerplate"),
      max_chars: z
        .number()
        .int()
        .min(1000)
        .optional()
        .describe("Optionally truncate the returned markdown to this many characters"),
      stealth: z
        .boolean()
        .default(false)
        .describe(
          "Force rendering through the Camoufox anti-detect browser. Slower; " +
            "use when a normal fetch is blocked (Cloudflare, bot walls, etc)."
        ),
    },
  },
  async ({ url, only_main_content, max_chars, stealth }) => {
    const data = await callGateway("/fetch", {
      url,
      only_main_content,
      max_chars: max_chars ?? null,
      stealth,
    });
    return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
  }
);

const transport = new StdioServerTransport();
await server.connect(transport);
console.error(`local-search MCP server running (gateway: ${GATEWAY_URL})`);
