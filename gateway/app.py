"""LLM-facing gateway over SearXNG (search) and Firecrawl (page fetching).

Endpoints:
  GET  /                    — web UI
  GET  /healthz             — liveness + upstream reachability
  GET  /search              — web search via SearXNG; optional content enrichment via Firecrawl
  POST /search              — same, JSON body
  POST /search/stream       — same, but streams progress events (SSE) before the result
  POST /fetch               — fetch a single URL as markdown via Firecrawl
  POST /fetch/stream        — same, but streams progress events (SSE) before the result
  GET  /history             — recent run history (SQLite-backed)
  GET  /history/{id}        — one run with its full event timeline + request
  DELETE /history/{id}      — delete one run
  DELETE /history           — clear history
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("gateway")

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8888").rstrip("/")
FIRECRAWL_URL = os.environ.get("FIRECRAWL_URL", "http://localhost:3002").rstrip("/")
CAMOUFOX_URL = os.environ.get("CAMOUFOX_URL", "http://localhost:3000").rstrip("/")
HISTORY_DB = os.environ.get("HISTORY_DB", str(Path(__file__).parent / "history.db"))
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="local-search gateway", version="1.1.0")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")

client = httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0))


SUPPORTED_FORMATS = {"markdown", "html", "rawHtml", "links", "screenshot", "json"}


# ── Structured JSON: decompose scraped markdown into nested sections ──

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _strip_inline(text: str) -> str:
    """Reduce inline markdown to plain text (images → alt, links → text)."""
    text = _IMAGE_RE.sub(lambda m: m.group(1), text)
    text = _LINK_RE.sub(lambda m: m.group(1), text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip().rstrip("\\").strip()  # firecrawl emits trailing \ hard-break markers


def markdown_to_structured(md: str) -> dict[str, Any]:
    """Parse markdown into a nested section tree keyed by heading hierarchy.

    Each section carries: heading, level, text (paragraphs), list (bullet/
    numbered items), links [{text,url}], images [{alt,src}], code (fenced
    blocks), sections (children). Empty fields are omitted.
    """

    def new_section(heading: str | None, level: int) -> dict[str, Any]:
        return {
            "heading": heading, "level": level,
            "paragraphs": [], "list": [], "links": [], "images": [],
            "code": [], "sections": [],
        }

    root = new_section(None, 0)
    stack = [root]
    para: list[str] = []
    code_lines: list[str] | None = None  # non-None while inside a fence

    def flush_para():
        if para:
            stack[-1]["paragraphs"].append(" ".join(para))
            para.clear()

    def collect_inline(line: str):
        for alt, src in _IMAGE_RE.findall(line):
            stack[-1]["images"].append({"alt": alt, "src": src})
        for text, url in _LINK_RE.findall(_IMAGE_RE.sub("", line)):
            stack[-1]["links"].append({"text": _strip_inline(text), "url": url})

    for line in (md or "").splitlines():
        if code_lines is not None:
            if line.strip().startswith("```"):
                stack[-1]["code"].append("\n".join(code_lines))
                code_lines = None
            else:
                code_lines.append(line)
            continue
        if line.strip().startswith("```"):
            flush_para()
            code_lines = []
            continue
        m = _HEADING_RE.match(line)
        if m:
            flush_para()
            level = len(m.group(1))
            while stack[-1]["level"] >= level:
                stack.pop()
            sec = new_section(_strip_inline(m.group(2)), level)
            stack[-1]["sections"].append(sec)
            stack.append(sec)
            continue
        m = _BULLET_RE.match(line)
        if m:
            flush_para()
            collect_inline(m.group(1))
            item = _strip_inline(m.group(1))
            if item:
                stack[-1]["list"].append(item)
            continue
        if not line.strip():
            flush_para()
            continue
        collect_inline(line)
        text = _strip_inline(line)
        if text:
            para.append(text)
    flush_para()
    if code_lines is not None:  # unterminated fence
        stack[-1]["code"].append("\n".join(code_lines))

    def finalize(sec: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if sec["heading"] is not None or sec["level"]:
            out["heading"] = sec["heading"]
            out["level"] = sec["level"]
        if sec["paragraphs"]:
            out["text"] = "\n\n".join(sec["paragraphs"])
        for key in ("list", "links", "images", "code"):
            if sec[key]:
                out[key] = sec[key]
        children = [finalize(s) for s in sec["sections"]]
        if children:
            out["sections"] = children
        return out

    top = finalize(root)
    sections = top.pop("sections", [])
    # Preamble (content before the first heading) becomes a heading-less section.
    if top:
        sections.insert(0, {"heading": None, "level": 0, **top})
    return {"sections": sections}


def _count_sections(sections: list[dict[str, Any]]) -> int:
    return sum(1 + _count_sections(s.get("sections", [])) for s in sections)


# ── Run log: timestamped progress events, mirrored to server logs, ──
# ── optionally streamed to the client, and persisted to history.   ──

class RunLog:
    def __init__(self, kind: str, label: str):
        self.kind = kind
        self.label = label
        self.started_at = datetime.now(timezone.utc)
        self.t0 = time.monotonic()
        self.events: list[dict[str, Any]] = []
        self.queue: asyncio.Queue | None = None

    def emit(self, stage: str, message: str):
        ev = {
            "t_ms": int((time.monotonic() - self.t0) * 1000),
            "stage": stage,
            "message": message,
        }
        self.events.append(ev)
        logger.info("[%s %r] %s: %s", self.kind, self.label, stage, message)
        if self.queue is not None:
            self.queue.put_nowait({"type": "event", **ev})

    @property
    def duration_ms(self) -> int:
        return int((time.monotonic() - self.t0) * 1000)


# ── Run history (SQLite) ──

def _history_connect() -> sqlite3.Connection:
    Path(HISTORY_DB).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(HISTORY_DB, check_same_thread=False)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            label TEXT,
            status TEXT NOT NULL,
            error TEXT,
            started_at TEXT NOT NULL,
            duration_ms INTEGER,
            request TEXT,
            summary TEXT,
            events TEXT
        )"""
    )
    conn.commit()
    return conn


_db = _history_connect()
_db_lock = asyncio.Lock()


async def save_run(
    log: RunLog,
    request: dict[str, Any],
    status: str,
    summary: dict[str, Any] | None = None,
    error: str | None = None,
):
    row = (
        log.kind, log.label, status, error,
        log.started_at.isoformat(), log.duration_ms,
        json.dumps(request), json.dumps(summary or {}), json.dumps(log.events),
    )

    def _insert():
        _db.execute(
            "INSERT INTO runs (kind, label, status, error, started_at, duration_ms,"
            " request, summary, events) VALUES (?,?,?,?,?,?,?,?,?)",
            row,
        )
        _db.commit()

    try:
        async with _db_lock:
            await asyncio.to_thread(_insert)
    except Exception:
        logger.exception("failed to record run history")


def _row_to_run(row: sqlite3.Row, full: bool) -> dict[str, Any]:
    out = {
        "id": row["id"],
        "kind": row["kind"],
        "label": row["label"],
        "status": row["status"],
        "error": row["error"],
        "started_at": row["started_at"],
        "duration_ms": row["duration_ms"],
        "summary": json.loads(row["summary"] or "{}"),
    }
    if full:
        out["request"] = json.loads(row["request"] or "{}")
        out["events"] = json.loads(row["events"] or "[]")
    else:
        out["event_count"] = len(json.loads(row["events"] or "[]"))
    return out


@app.get("/history")
async def history_list(limit: int = 50, offset: int = 0):
    def _q():
        _db.row_factory = sqlite3.Row
        return _db.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ? OFFSET ?",
            (min(max(limit, 1), 200), max(offset, 0)),
        ).fetchall()

    async with _db_lock:
        rows = await asyncio.to_thread(_q)
    return {"runs": [_row_to_run(r, full=False) for r in rows]}


@app.get("/history/{run_id}")
async def history_get(run_id: int):
    def _q():
        _db.row_factory = sqlite3.Row
        return _db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()

    async with _db_lock:
        row = await asyncio.to_thread(_q)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
    return _row_to_run(row, full=True)


@app.delete("/history/{run_id}")
async def history_delete(run_id: int):
    def _q():
        cur = _db.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        _db.commit()
        return cur.rowcount

    async with _db_lock:
        deleted = await asyncio.to_thread(_q)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
    return {"deleted": run_id}


@app.delete("/history")
async def history_clear():
    def _q():
        cur = _db.execute("DELETE FROM runs")
        _db.commit()
        return cur.rowcount

    async with _db_lock:
        deleted = await asyncio.to_thread(_q)
    return {"deleted": deleted}


class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query, like you would type into Google")
    max_results: int = Field(8, ge=1, le=30, description="Max results to return")
    fetch_content: bool = Field(
        False, description="If true, scrape the top results and include page markdown"
    )
    fetch_top: int = Field(3, ge=1, le=10, description="How many top results to scrape when fetch_content is true")
    fetch_formats: list[str] = Field(
        ["markdown"],
        description="Formats to scrape when fetch_content is true: markdown/html/rawHtml/links/json/screenshot",
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
        description="Output formats to return. Any of: markdown, html, rawHtml, links, json "
        "(markdown decomposed into nested sections), screenshot",
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


async def searx_search(req: SearchRequest, log: RunLog) -> list[dict[str, Any]]:
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
    log.emit("search", f"querying searxng for “{req.query}”")
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
    log.emit("search", f"{len(results)} results from searxng")
    return results


async def camoufox_screenshot(
    url: str, wait_for: int | None, timeout: int, log: RunLog
) -> dict[str, Any]:
    payload: dict[str, Any] = {"url": url, "timeout": timeout, "full_page": True}
    if wait_for:
        payload["wait_after_load"] = wait_for
    # Camoufox's worst case is goto(timeout) + capture(timeout) + viewport
    # fallback; the global 90s client timeout would abandon requests camoufox
    # is still legitimately working on. Budget the call from the payload.
    call_timeout = httpx.Timeout(timeout / 1000 * 2 + 45, connect=10.0)
    # Navigation time varies a lot on throttled/heavy sites; one retry
    # absorbs most transient goto timeouts.
    last_exc: Exception | None = None
    for attempt in range(1, 3):
        log.emit(
            "screenshot",
            f"rendering full-page screenshot of {url} via camoufox"
            + (f" (retry {attempt - 1})" if attempt > 1 else ""),
        )
        try:
            r = await client.post(f"{CAMOUFOX_URL}/screenshot", json=payload, timeout=call_timeout)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Surface camoufox's own error message, not just the status line.
            try:
                detail = e.response.json().get("error") or e.response.text[:300]
            except Exception:
                detail = e.response.text[:300] or str(e)
            log.emit("screenshot", f"attempt {attempt} failed: {detail}")
            last_exc = HTTPException(
                status_code=502, detail=f"Camoufox screenshot failed for {url}: {detail}"
            )
            continue
        except httpx.HTTPError as e:
            # str() of httpx timeouts is often empty; include the class name.
            detail = f"{type(e).__name__}: {e}".rstrip(": ")
            log.emit("screenshot", f"attempt {attempt} failed: {detail}")
            last_exc = HTTPException(
                status_code=502, detail=f"Camoufox screenshot error for {url}: {detail}"
            )
            continue
        body = r.json()
        if body.get("screenshot"):
            note = f" — {body['degraded']}" if body.get("degraded") else ""
            log.emit(
                "screenshot",
                f"captured {url} ({len(body['screenshot']) * 3 // 4 // 1024} KB png){note}",
            )
            return body
        last_exc = HTTPException(
            status_code=502, detail=f"Camoufox returned no screenshot for {url}"
        )
    if isinstance(last_exc, HTTPException):
        raise last_exc
    raise HTTPException(
        status_code=502, detail=f"Camoufox screenshot error for {url}: {last_exc}"
    ) from last_exc


async def firecrawl_scrape(req: FetchRequest, log: RunLog) -> dict[str, Any]:
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
    want_json = "json" in formats
    # json is derived from markdown server-side, so ensure markdown is scraped.
    fc_formats = [f for f in formats if f not in ("screenshot", "json")]
    if want_json and "markdown" not in fc_formats:
        fc_formats.append("markdown")

    def attach_json(page: dict[str, Any]) -> dict[str, Any]:
        if not want_json:
            return page
        structure = markdown_to_structured(page.get("markdown") or "")
        log.emit(
            "structure",
            f"parsed markdown into {_count_sections(structure['sections'])} sections",
        )
        page["json"] = {"title": page.get("title"), "url": page.get("url"), **structure}
        if "markdown" not in formats:
            page.pop("markdown", None)
        page["formats"] = formats
        return page

    if want_screenshot and not fc_formats:
        shot = await camoufox_screenshot(req.url, req.wait_for, shot_timeout, log)
        return {
            "url": req.url,
            "title": shot.get("title"),
            "description": None,
            "status_code": shot.get("pageStatusCode"),
            "language": None,
            "source_url": req.url,
            "formats": formats,
            "screenshot": shot["screenshot"],
            **({"screenshot_note": shot["degraded"]} if shot.get("degraded") else {}),
        }

    if want_screenshot:
        page, shot = await asyncio.gather(
            _firecrawl_request(req, fc_formats, timeout, log),
            camoufox_screenshot(req.url, req.wait_for, shot_timeout, log),
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
            if shot.get("degraded"):
                page["screenshot_note"] = shot["degraded"]
        return attach_json(page)

    return attach_json(await _firecrawl_request(req, fc_formats, timeout, log))


async def _firecrawl_request(
    req: FetchRequest, formats: list[str], timeout: int, log: RunLog
) -> dict[str, Any]:
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

    log.emit(
        "scrape",
        f"scraping {req.url} as {'/'.join(formats)} via firecrawl"
        + (" (camoufox stealth)" if req.stealth else ""),
    )
    headers = {"Authorization": "Bearer local"}  # self-hosted: auth disabled, header ignored
    try:
        r = await client.post(f"{FIRECRAWL_URL}/v2/scrape", json=payload, headers=headers)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.emit("scrape", f"firecrawl error for {req.url}: {e}")
        raise HTTPException(status_code=502, detail=f"Firecrawl error for {req.url}: {e}") from e
    body = r.json()
    if not body.get("success"):
        log.emit("scrape", f"firecrawl failed for {req.url}: {body.get('error')}")
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
    md_len = len(out.get("markdown") or "")
    log.emit(
        "scrape",
        f"scraped {req.url} (HTTP {meta.get('statusCode', '?')}"
        + (f", {md_len:,} chars markdown" if md_len else "")
        + ")",
    )
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


async def _run_search(req: SearchRequest, log: RunLog) -> dict[str, Any]:
    results = await searx_search(req, log)
    if req.fetch_content and results:
        top = results[: req.fetch_top]
        log.emit(
            "enrich",
            f"scraping top {len(top)} result{'s' if len(top) != 1 else ''} "
            f"as {'/'.join(req.fetch_formats)}",
        )

        async def safe_scrape(item):
            try:
                sub = FetchRequest(
                    url=item["url"],
                    formats=req.fetch_formats,
                    stealth=req.fetch_stealth,
                )
                page = await firecrawl_scrape(sub, log)
                # Surface requested formats on the result card.
                # (fmt = requested format name, src = key in the scrape output, dest = key on the result)
                for fmt, src, dest in (
                    ("markdown", "markdown", "content"),
                    ("html", "html", "html"),
                    ("rawHtml", "raw_html", "raw_html"),
                    ("links", "links", "links"),
                    ("json", "json", "json"),
                    ("screenshot", "screenshot", "screenshot"),
                ):
                    if fmt in req.fetch_formats and page.get(src) is not None:
                        item[dest] = page[src]
                if page.get("screenshot_error"):
                    item["screenshot_error"] = page["screenshot_error"]
            except HTTPException as e:
                log.emit("enrich", f"scrape failed for {item['url']}: {e.detail}")
                item["content_error"] = e.detail

        await asyncio.gather(*(safe_scrape(item) for item in top))
        log.emit("enrich", "enrichment complete")
    return {"query": req.query, "result_count": len(results), "results": results}


def _search_summary(result: dict[str, Any]) -> dict[str, Any]:
    results = result.get("results", [])
    return {
        "result_count": result.get("result_count", 0),
        "scraped": sum(
            1 for r in results if any(k in r for k in ("content", "html", "raw_html", "links", "json", "screenshot"))
        ),
        "scrape_errors": sum(1 for r in results if "content_error" in r),
        "screenshots": sum(1 for r in results if "screenshot" in r),
    }


def _fetch_summary(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": page.get("title"),
        "status_code": page.get("status_code"),
        "formats": page.get("formats"),
        "markdown_chars": len(page.get("markdown") or "") or None,
        "json_sections": (
            _count_sections(page["json"].get("sections", [])) if page.get("json") else None
        ),
        "screenshot": "screenshot" in page,
        "screenshot_error": page.get("screenshot_error"),
        "screenshot_note": page.get("screenshot_note"),
    }


# ── Endpoint plumbing: run + record history; optionally stream events ──

async def _run_recorded(kind, label, request_payload, runner, summary_fn, log: RunLog):
    try:
        result = await runner(log)
    except HTTPException as e:
        log.emit("done", f"failed: {e.detail}")
        await save_run(log, request_payload, status="error", error=str(e.detail))
        raise
    except Exception as e:
        logger.exception("[%s %r] unexpected failure", kind, label)
        log.emit("done", f"failed: {e}")
        await save_run(log, request_payload, status="error", error=str(e))
        raise
    log.emit("done", f"completed in {log.duration_ms / 1000:.1f}s")
    await save_run(log, request_payload, status="ok", summary=summary_fn(result))
    return result


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _stream_response(kind, label, request_payload, runner, summary_fn) -> StreamingResponse:
    log = RunLog(kind, label)
    log.queue = asyncio.Queue()

    async def work():
        try:
            result = await _run_recorded(kind, label, request_payload, runner, summary_fn, log)
            log.queue.put_nowait({"type": "result", "data": result})
        except HTTPException as e:
            log.queue.put_nowait({"type": "error", "error": str(e.detail)})
        except Exception as e:
            log.queue.put_nowait({"type": "error", "error": str(e)})

    async def gen():
        task = asyncio.create_task(work())
        try:
            while True:
                ev = await log.queue.get()
                yield _sse(ev)
                if ev["type"] in ("result", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/search")
async def search_post(req: SearchRequest):
    log = RunLog("search", req.query)
    return await _run_recorded(
        "search", req.query, req.model_dump(), lambda l: _run_search(req, l), _search_summary, log
    )


@app.post("/search/stream")
async def search_stream(req: SearchRequest):
    return _stream_response(
        "search", req.query, req.model_dump(), lambda l: _run_search(req, l), _search_summary
    )


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
    log = RunLog("search", req.query)
    return await _run_recorded(
        "search", req.query, req.model_dump(), lambda l: _run_search(req, l), _search_summary, log
    )


async def _run_fetch(req: FetchRequest, log: RunLog) -> dict[str, Any]:
    page = await firecrawl_scrape(req, log)
    if req.max_chars and page.get("markdown"):
        if len(page["markdown"]) > req.max_chars:
            page["markdown"] = page["markdown"][: req.max_chars]
            page["truncated"] = True
            page["truncated_at"] = req.max_chars
    return page


@app.post("/fetch")
async def fetch(req: FetchRequest):
    log = RunLog("fetch", req.url)
    return await _run_recorded(
        "fetch", req.url, req.model_dump(), lambda l: _run_fetch(req, l), _fetch_summary, log
    )


@app.post("/fetch/stream")
async def fetch_stream(req: FetchRequest):
    return _stream_response(
        "fetch", req.url, req.model_dump(), lambda l: _run_fetch(req, l), _fetch_summary
    )
