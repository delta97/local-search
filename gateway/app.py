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
CAMOUFOX_URL = os.environ.get("CAMOUFOX_URL", "http://localhost:3000").rstrip("/")
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="local-search gateway", version="1.0.0")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")

client = httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0))


SUPPORTED_FORMATS = {"markdown", "html", "rawHtml", "links", "screenshot"}


class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query, like you would type into Google")
    max_results: int = Field(8, ge=1, le=30, description="Max results to return")
    fetch_content: bool = Field(
        False, description="If true, scrape the top results and include page markdown"
    )
    fetch_top: int = Field(3, ge=1, le=10, description="How many top results to scrape when fetch_content is true")
    fetch_formats: list[str] = Field(
        ["markdown"],
        description="Formats to scrape when fetch_content is true: markdown/html/rawHtml/links/screenshot",
    )
    fetch_stealth: bool = Field(
        False,
        description="When enriching results, force rendering through the Camoufox anti-detect browser",
    )
    categories: str = Field("general", description="SearXNG categories, e.g. 'general', 'news', 'it'")
    language: str = Field("en", description="Search language code")
    engines: str | None = Field(None, description="Comma-separated SearXNG engine allowlist, e.g. 'google,bing'")
    pageno: int = Field(1, ge=1, description="Result page number (1-based)")
    safesearch: int = Field(0, ge=-1, le=2, description="Safe search level: 0 off, 1 mod, 2 strict")
    time_range: str | None = Field(None, description="Optional: 'day', 'week', 'month', or 'year'")


class FetchRequest(BaseModel):
    url: str = Field(..., description="URL to fetch")
    formats: list[str] = Field(
        ["markdown"],
        description="Output formats to return. Any of: markdown, html, rawHtml, links, screenshot",
    )
    only_main_content: bool = Field(True, description="Strip nav/footer boilerplate (applies to markdown/html)")
    include_tags: list[str] | None = Field(
        None, description="CSS selectors/tags to include (e.g. ['article', 'main'])"
    )
    exclude_tags: list[str] | None = Field(
        None, description="CSS selectors/tags to exclude (e.g. ['nav', 'footer', '.ads'])"
    )
    max_chars: int | None = Field(None, description="Optional truncation of returned markdown")
    max_tokens: int | None = Field(None, description="Optional LLM-token budget for the returned markdown")
    wait_for: int | None = Field(None, description="ms to wait on the page before extracting content")
    timeout: int | None = Field(None, description="Override scrape timeout in ms")
    location: str | None = Field(
        None, description="ISO-3166 country code to geo-route the request from, e.g. 'US'"
    )
    actions: list[dict[str, Any]] | None = Field(
        None,
        description="Pre-extract interactions for Firecrawl: "
        "[{type:'wait'|'click'|'scroll'|'screenshot'|'write'|'press', selector?, text?, ...}]",
    )
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
        "safesearch": str(req.safesearch),
        "pageno": str(req.pageno),
    }
    if req.engines:
        params["engines"] = req.engines
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
                "engines": item.get("engines"),
                "score": item.get("score"),
                "category": item.get("category"),
                "published_date": item.get("publishedDate"),
            }
        )
    return results


async def camoufox_screenshot(url: str, wait_for: int | None, timeout: int) -> dict[str, Any]:
    payload: dict[str, Any] = {"url": url, "timeout": timeout, "full_page": True}
    if wait_for:
        payload["wait_after_load"] = wait_for
    # Navigation time varies a lot on throttled/heavy sites; one retry
    # absorbs most transient goto timeouts.
    last_exc: Exception | None = None
    for _ in range(2):
        try:
            r = await client.post(f"{CAMOUFOX_URL}/screenshot", json=payload)
            r.raise_for_status()
        except httpx.HTTPError as e:
            last_exc = e
            continue
        body = r.json()
        if body.get("screenshot"):
            return body
        last_exc = HTTPException(
            status_code=502, detail=f"Camoufox returned no screenshot for {url}"
        )
    if isinstance(last_exc, HTTPException):
        raise last_exc
    raise HTTPException(
        status_code=502, detail=f"Camoufox screenshot error for {url}: {last_exc}"
    ) from last_exc


async def firecrawl_scrape(req: FetchRequest) -> dict[str, Any]:
    # Normalize requested formats; default to markdown for backward compat.
    formats = list(req.formats) if req.formats else ["markdown"]
    bad = [f for f in formats if f not in SUPPORTED_FORMATS]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format(s): {bad}. Supported: {sorted(SUPPORTED_FORMATS)}",
        )

    timeout = req.timeout or (60000 if req.stealth else 30000)
    # Self-hosted Firecrawl cannot produce screenshots (that lives in its
    # cloud-only fire-engine); camoufox captures them directly instead.
    # Screenshots get a more generous navigation budget than text scrapes.
    shot_timeout = req.timeout or 60000
    want_screenshot = "screenshot" in formats
    fc_formats = [f for f in formats if f != "screenshot"]

    if want_screenshot and not fc_formats:
        shot = await camoufox_screenshot(req.url, req.wait_for, shot_timeout)
        return {
            "url": req.url,
            "title": shot.get("title"),
            "description": None,
            "status_code": shot.get("pageStatusCode"),
            "language": None,
            "source_url": req.url,
            "formats": formats,
            "screenshot": shot["screenshot"],
        }

    if want_screenshot:
        page, shot = await asyncio.gather(
            _firecrawl_request(req, fc_formats, timeout),
            camoufox_screenshot(req.url, req.wait_for, shot_timeout),
            return_exceptions=True,
        )
        if isinstance(page, BaseException):
            raise page
        page["formats"] = formats
        if isinstance(shot, BaseException):
            page["screenshot_error"] = (
                shot.detail if isinstance(shot, HTTPException) else str(shot)
            )
        else:
            page["screenshot"] = shot["screenshot"]
        return page

    return await _firecrawl_request(req, fc_formats, timeout)


async def _firecrawl_request(req: FetchRequest, formats: list[str], timeout: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "url": req.url,
        "formats": formats,
        "onlyMainContent": req.only_main_content,
        "timeout": timeout,
    }
    if req.wait_for is not None:
        payload["waitFor"] = req.wait_for
    if req.include_tags:
        payload["includeTags"] = req.include_tags
    if req.exclude_tags:
        payload["excludeTags"] = req.exclude_tags
    if req.max_tokens is not None:
        payload["maxTokens"] = req.max_tokens
    if req.location:
        payload["location"] = {"country": req.location}
    if req.actions:
        payload["actions"] = req.actions
    if req.stealth:
        # waitFor forces Firecrawl to use the browser rendering engine
        # (PLAYWRIGHT_MICROSERVICE_URL → camoufox) instead of plain HTTP fetch.
        payload.setdefault("waitFor", 500)

    headers = {"Authorization": "Bearer local"}  # self-hosted: auth disabled, header ignored
    try:
        r = await client.post(f"{FIRECRAWL_URL}/v2/scrape", json=payload, headers=headers)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Firecrawl error for {req.url}: {e}") from e
    body = r.json()
    if not body.get("success"):
        raise HTTPException(
            status_code=502, detail=f"Firecrawl failed for {req.url}: {body.get('error')}"
        )
    data = body.get("data", {})
    meta = data.get("metadata", {})

    out: dict[str, Any] = {
        "url": req.url,
        "title": meta.get("title"),
        "description": meta.get("description"),
        "status_code": meta.get("statusCode"),
        "language": meta.get("language"),
        "source_url": meta.get("sourceURL"),
        "formats": formats,
    }
    # Include only the formats the caller asked for (keeps payloads small).
    if "markdown" in formats:
        out["markdown"] = data.get("markdown")
    if "html" in formats:
        out["html"] = data.get("html")
    if "rawHtml" in formats:
        out["raw_html"] = data.get("rawHtml")
    if "links" in formats:
        out["links"] = data.get("links")
    return out


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
    try:
        r = await client.get(f"{CAMOUFOX_URL}/health", timeout=10)
        status["camoufox"] = "ok" if r.status_code == 200 else f"http {r.status_code}"
    except Exception as e:
        status["camoufox"] = f"unreachable: {e}"
    return status


async def _run_search(req: SearchRequest) -> dict[str, Any]:
    results = await searx_search(req)
    if req.fetch_content and results:
        top = results[: req.fetch_top]

        async def safe_scrape(item):
            try:
                sub = FetchRequest(
                    url=item["url"],
                    formats=req.fetch_formats,
                    stealth=req.fetch_stealth,
                )
                page = await firecrawl_scrape(sub)
                # Surface requested formats on the result card.
                # (fmt = requested format name, src = key in the scrape output, dest = key on the result)
                for fmt, src, dest in (
                    ("markdown", "markdown", "content"),
                    ("html", "html", "html"),
                    ("rawHtml", "raw_html", "raw_html"),
                    ("links", "links", "links"),
                    ("screenshot", "screenshot", "screenshot"),
                ):
                    if fmt in req.fetch_formats and page.get(src) is not None:
                        item[dest] = page[src]
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
    fetch_stealth: bool = False,
    categories: str = "general",
    language: str = "en",
    engines: str | None = None,
    pageno: int = 1,
    safesearch: int = 0,
    time_range: str | None = None,
):
    req = SearchRequest(
        query=q,
        max_results=max_results,
        fetch_content=fetch_content,
        fetch_top=fetch_top,
        fetch_formats=["markdown"],  # GET defaults to markdown; use POST for other formats
        fetch_stealth=fetch_stealth,
        categories=categories,
        language=language,
        engines=engines,
        pageno=pageno,
        safesearch=safesearch,
        time_range=time_range,
    )
    return await _run_search(req)


@app.post("/fetch")
async def fetch(req: FetchRequest):
    page = await firecrawl_scrape(req)
    if req.max_chars and page.get("markdown"):
        if len(page["markdown"]) > req.max_chars:
            page["markdown"] = page["markdown"][: req.max_chars]
            page["truncated"] = True
            page["truncated_at"] = req.max_chars
    return page
