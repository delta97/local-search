"""LLM-facing gateway over SearXNG (search) and Firecrawl (page fetching).

Endpoints:
  GET  /                    — web UI
  GET  /healthz            — liveness + upstream reachability
  GET  /search             — web search via SearXNG; optional content enrichment via Firecrawl
  POST /search             — same, JSON body
  POST /fetch              — fetch a single URL as markdown via Firecrawl
"""

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8888").rstrip("/")
FIRECRAWL_URL = os.environ.get("FIRECRAWL_URL", "http://localhost:3002").rstrip("/")
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="local-search gateway", version="1.0.0")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")

client = httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0))


class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query, like you would type into Google")
    max_results: int = Field(8, ge=1, le=30, description="Max results to return")
    fetch_content: bool = Field(
        False, description="If true, scrape the top results and include page markdown"
    )
    fetch_top: int = Field(3, ge=1, le=10, description="How many top results to scrape when fetch_content is true")
    categories: str = Field("general", description="SearXNG categories, e.g. 'general', 'news', 'it'")
    language: str = Field("en", description="Search language code")
    time_range: str | None = Field(None, description="Optional: 'day', 'week', 'month', or 'year'")


class FetchRequest(BaseModel):
    url: str = Field(..., description="URL to fetch")
    only_main_content: bool = Field(True, description="Strip nav/footer boilerplate")
    max_chars: int | None = Field(None, description="Optional truncation of returned markdown")
    stealth: bool = Field(
        False,
        description="Force rendering through the Camoufox anti-detect browser "
        "(slower; use for bot-protected sites)",
    )


async def searx_search(req: SearchRequest) -> list[dict[str, Any]]:
    params = {
        "q": req.query,
        "format": "json",
        "categories": req.categories,
        "language": req.language,
        "safesearch": "0",
    }
    if req.time_range:
        params["time_range"] = req.time_range
    try:
        r = await client.get(f"{SEARXNG_URL}/search", params=params)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"SearXNG error: {e}") from e
    results = []
    for item in r.json().get("results", [])[: req.max_results]:
        results.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "snippet": item.get("content"),
                "engine": item.get("engine"),
                "score": item.get("score"),
                "published_date": item.get("publishedDate"),
            }
        )
    return results


async def firecrawl_scrape(
    url: str, only_main_content: bool = True, stealth: bool = False
) -> dict[str, Any]:
    payload = {
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": only_main_content,
        "timeout": 60000 if stealth else 30000,
    }
    if stealth:
        # waitFor forces Firecrawl to use the browser rendering engine
        # (PLAYWRIGHT_MICROSERVICE_URL → camoufox) instead of plain HTTP fetch.
        payload["waitFor"] = 500
    headers = {"Authorization": "Bearer local"}  # self-hosted: auth disabled, header ignored
    try:
        r = await client.post(f"{FIRECRAWL_URL}/v2/scrape", json=payload, headers=headers)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Firecrawl error for {url}: {e}") from e
    body = r.json()
    if not body.get("success"):
        raise HTTPException(status_code=502, detail=f"Firecrawl failed for {url}: {body.get('error')}")
    data = body.get("data", {})
    meta = data.get("metadata", {})
    return {
        "url": url,
        "title": meta.get("title"),
        "description": meta.get("description"),
        "markdown": data.get("markdown"),
        "status_code": meta.get("statusCode"),
    }


@app.get("/healthz")
async def healthz():
    status = {"gateway": "ok"}
    try:
        r = await client.get(f"{SEARXNG_URL}/search", params={"q": "ping", "format": "json"}, timeout=10)
        status["searxng"] = "ok" if r.status_code == 200 else f"http {r.status_code}"
    except Exception as e:
        status["searxng"] = f"unreachable: {e}"
    try:
        r = await client.get(f"{FIRECRAWL_URL}/", timeout=10)
        status["firecrawl"] = "ok" if r.status_code < 500 else f"http {r.status_code}"
    except Exception as e:
        status["firecrawl"] = f"unreachable: {e}"
    return status


async def _run_search(req: SearchRequest) -> dict[str, Any]:
    results = await searx_search(req)
    if req.fetch_content and results:
        top = results[: req.fetch_top]

        async def safe_scrape(item):
            try:
                page = await firecrawl_scrape(item["url"])
                item["content"] = page["markdown"]
            except HTTPException as e:
                item["content_error"] = e.detail

        await asyncio.gather(*(safe_scrape(item) for item in top))
    return {"query": req.query, "result_count": len(results), "results": results}


@app.post("/search")
async def search_post(req: SearchRequest):
    return await _run_search(req)


@app.get("/search")
async def search_get(
    q: str,
    max_results: int = 8,
    fetch_content: bool = False,
    fetch_top: int = 3,
    categories: str = "general",
    language: str = "en",
    time_range: str | None = None,
):
    req = SearchRequest(
        query=q,
        max_results=max_results,
        fetch_content=fetch_content,
        fetch_top=fetch_top,
        categories=categories,
        language=language,
        time_range=time_range,
    )
    return await _run_search(req)


@app.post("/fetch")
async def fetch(req: FetchRequest):
    page = await firecrawl_scrape(req.url, req.only_main_content, req.stealth)
    if req.max_chars and page.get("markdown"):
        if len(page["markdown"]) > req.max_chars:
            page["markdown"] = page["markdown"][: req.max_chars]
            page["truncated"] = True
    return page
