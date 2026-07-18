"""LLM-facing gateway over SearXNG (search) and Firecrawl (page fetching).

Endpoints:
  GET  /                    — web UI
  GET  /healthz             — liveness + upstream reachability
  GET  /search              — web search via SearXNG; optional content enrichment via Firecrawl,
                              domain/date filters, optional LLM answer synthesis (OpenRouter)
  POST /search              — same, JSON body
  POST /search/stream       — same, but streams progress events (SSE) before the result
  POST /fetch               — fetch one URL (or a batch of up to 20) via Firecrawl;
                              PDFs are parsed locally with pypdf; optional LLM page summaries
  POST /fetch/stream        — same, but streams progress events (SSE) before the result
  POST /crawl               — crawl a site via Firecrawl (sync facade over its async job API);
                              optional LLM per-page summaries
  POST /crawl/stream        — same, with SSE progress ticks while pages are crawled
  POST /navigate            — LLM-guided goal-directed walk: the model follows links toward a
                              natural-language goal and returns a cited answer + visited trail
  POST /navigate/stream     — same, with SSE progress per step
  POST /map                 — discover a site's URLs via Firecrawl map (no scraping)
  POST /map/stream          — same, SSE
  GET  /history             — recent run history (SQLite-backed)
  GET  /history/{id}        — one run with its full event timeline + request
  DELETE /history/{id}      — delete one run
  DELETE /history           — clear history
"""

import asyncio
import io
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse, urljoin
import xml.etree.ElementTree as ET

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator
from pypdf import PdfReader
from pypdf.errors import PdfReadError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("gateway")

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8888").rstrip("/")
FIRECRAWL_URL = os.environ.get("FIRECRAWL_URL", "http://localhost:3002").rstrip("/")
# Direct-browser service (camoufox or botasaurus — same HTTP contract).
# CAMOUFOX_URL kept as a fallback for older deployments.
BROWSER_URL = (
    os.environ.get("BROWSER_URL") or os.environ.get("CAMOUFOX_URL") or "http://localhost:3000"
).rstrip("/")
HISTORY_DB = os.environ.get("HISTORY_DB", str(Path(__file__).parent / "history.db"))
STATIC_DIR = Path(__file__).parent / "static"

# Answer synthesis (OpenRouter or any OpenAI-compatible endpoint).
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "openai/gpt-4o-mini")
ANSWER_BASE_URL = os.environ.get("ANSWER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")

FETCH_BATCH_MAX = 20
FETCH_BATCH_CONCURRENCY = 5  # matches camoufox MAX_CONCURRENT_PAGES (botasaurus defaults to 3)
PDF_MAX_BYTES = 20 * 1024 * 1024
CRAWL_MAX_LIMIT = 100

FIRECRAWL_HEADERS = {"Authorization": "Bearer local"}  # self-hosted: auth disabled, header ignored

app = FastAPI(title="local-search gateway", version="1.3.0")


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
    include_domains: list[str] | None = Field(
        None, max_length=10,
        description="Only return results whose host is (a subdomain of) one of these domains",
    )
    exclude_domains: list[str] | None = Field(
        None, max_length=10, description="Drop results whose host matches any of these domains"
    )
    start_date: str | None = Field(
        None, description="YYYY-MM-DD; drop results published before this (undated results are kept)"
    )
    end_date: str | None = Field(
        None, description="YYYY-MM-DD; drop results published after this (undated results are kept)"
    )
    include_answer: bool | Literal["basic", "advanced"] = Field(
        False,
        description="Synthesize a cited answer from top results via LLM. true/'basic' = "
        "titles+snippets; 'advanced' = also use scraped content when fetch_content is on",
    )


class FetchRequest(BaseModel):
    url: str | None = Field(None, description="URL to fetch (exactly one of url/urls)")
    urls: list[str] | None = Field(
        None, min_length=1, max_length=FETCH_BATCH_MAX,
        description=f"Batch: up to {FETCH_BATCH_MAX} URLs fetched concurrently",
    )
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
    summarize: bool = Field(
        False,
        description="Attach an LLM-generated summary to each page (requires OPENROUTER_API_KEY)",
    )

    @model_validator(mode="after")
    def _one_of_url_urls(self):
        if bool(self.url) == bool(self.urls):
            raise ValueError("Provide exactly one of 'url' or 'urls'")
        return self


# ── Domain / date filters for search ──

def _norm_domain(d: str) -> str:
    d = d.strip().lower()
    if "//" in d:
        d = urlparse(d).netloc or d.split("//", 1)[1]
    d = d.split("/", 1)[0].split(":", 1)[0]
    for prefix in ("www.", "*."):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d


def _host_matches(url: str, domains: list[str]) -> bool:
    host = (urlparse(url).netloc or "").lower().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return any(host == d or host.endswith("." + d) for d in domains)


def _parse_result_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.rstrip("Z"))
    except ValueError:
        return None


def _passes_filters(
    item: dict[str, Any],
    include: list[str],
    exclude: list[str],
    start: datetime | None,
    end: datetime | None,
) -> bool:
    url = item.get("url") or ""
    if include and not _host_matches(url, include):
        return False
    if exclude and _host_matches(url, exclude):
        return False
    if start or end:
        published = _parse_result_date(item.get("published_date"))
        # Undated results are kept: SearXNG omits dates for most results and
        # dropping them would empty result sets.
        if published is not None:
            if start and published < start:
                return False
            if end and published > end:
                return False
    return True


async def searx_search(req: SearchRequest, log: RunLog) -> list[dict[str, Any]]:
    include = [_norm_domain(d) for d in (req.include_domains or []) if _norm_domain(d)]
    exclude = [_norm_domain(d) for d in (req.exclude_domains or []) if _norm_domain(d)]
    start = _parse_result_date(req.start_date)
    end = _parse_result_date(req.end_date)
    filtering = bool(include or exclude or start or end)

    # Query rewriting is only a recall booster (site: syntax is engine-
    # dependent); the post-filter below is authoritative either way.
    query = req.query
    if include and len(include) <= 3:
        sites = " OR ".join(f"site:{d}" for d in include)
        query += f" ({sites})" if len(include) > 1 else f" {sites}"
    if exclude and len(exclude) <= 3:
        query += "".join(f" -site:{d}" for d in exclude)

    params = {
        "q": query,
        "format": "json",
        "categories": req.categories,
        "language": req.language,
        "safesearch": str(req.safesearch),
    }
    if req.engines:
        params["engines"] = req.engines
    if req.time_range:
        params["time_range"] = req.time_range

    async def _page(pageno: int) -> list[dict[str, Any]]:
        try:
            r = await client.get(
                f"{SEARXNG_URL}/search", params={**params, "pageno": str(pageno)}
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"SearXNG error: {e}") from e
        return [
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
            for item in r.json().get("results", [])
        ]

    log.emit("search", f"querying searxng for “{query}”")
    kept: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_total = 0
    # With filters active, overfetch up to 3 pages to still fill max_results.
    for pageno in range(req.pageno, req.pageno + (3 if filtering else 1)):
        raw = await _page(pageno)
        seen_total += len(raw)
        for item in raw:
            url = item.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            if _passes_filters(item, include, exclude, start, end):
                kept.append(item)
        if not raw or len(kept) >= req.max_results:
            break
    if filtering:
        log.emit("filter", f"kept {len(kept)}/{seen_total} results after domain/date filters")
    results = kept[: req.max_results]
    log.emit("search", f"{len(results)} results from searxng")
    return results


def _apply_max_chars(page: dict[str, Any], max_chars: int | None) -> dict[str, Any]:
    if max_chars and page.get("markdown") and len(page["markdown"]) > max_chars:
        page["markdown"] = page["markdown"][:max_chars]
        page["truncated"] = True
        page["truncated_at"] = max_chars
    return page


def _normalize_fc_page(
    data: dict[str, Any], formats: list[str], url: str | None = None
) -> dict[str, Any]:
    """Map a Firecrawl page payload (scrape or crawl) onto our response shape."""
    meta = data.get("metadata", {}) or {}
    out: dict[str, Any] = {
        "url": url or meta.get("url") or meta.get("sourceURL"),
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


# ── PDF extraction: self-hosted Firecrawl can't parse PDFs, so the gateway ──
# ── downloads and parses them locally with pypdf.                          ──

def _looks_like_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _parse_pdf(data: bytes) -> tuple[list[str], str | None]:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"PDF is encrypted: {e}") from e
        pages = [page.extract_text() or "" for page in reader.pages]
        title = reader.metadata.title if reader.metadata else None
        return pages, title
    except PdfReadError as e:
        raise HTTPException(status_code=502, detail=f"Failed to parse PDF: {e}") from e


async def fetch_pdf(req: FetchRequest, log: RunLog, sniff: bool = False) -> dict[str, Any] | None:
    """Download req.url and parse it as a PDF.

    With sniff=True this is a fallback probe: returns None (instead of
    raising) when the body isn't actually a PDF or the download fails.
    """
    formats = list(req.formats) if req.formats else ["markdown"]
    log.emit("pdf", f"downloading {req.url} (pdf path, {PDF_MAX_BYTES // 2**20}MB cap)")
    buf = bytearray()
    try:
        # The shared client doesn't follow redirects; PDFs frequently live
        # behind them (arxiv, DOI resolvers, signed S3 URLs).
        async with client.stream(
            "GET",
            req.url,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0)"},
        ) as r:
            r.raise_for_status()
            status_code = r.status_code
            final_url = str(r.url)
            async for chunk in r.aiter_bytes():
                buf += chunk
                if sniff and len(buf) >= 5 and not bytes(buf[:5]) == b"%PDF-":
                    return None
                if len(buf) > PDF_MAX_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"PDF exceeds {PDF_MAX_BYTES // 2**20}MB cap: {req.url}",
                    )
    except HTTPException:
        raise
    except httpx.HTTPError as e:
        if sniff:
            return None
        detail = f"{type(e).__name__}: {e}".rstrip(": ")
        raise HTTPException(
            status_code=502, detail=f"PDF download failed for {req.url}: {detail}"
        ) from e
    if bytes(buf[:5]) != b"%PDF-":
        if sniff:
            return None
        raise HTTPException(status_code=502, detail=f"{req.url} does not look like a PDF")

    pages_text, meta_title = await asyncio.to_thread(_parse_pdf, bytes(buf))
    log.emit("pdf", f"parsed {len(pages_text)} pages from {len(buf) // 1024} KB pdf")
    body_md = "\n\n".join(
        f"## Page {i}\n\n{t.strip()}" for i, t in enumerate(pages_text, 1) if t.strip()
    )
    out: dict[str, Any] = {
        "url": req.url,
        "title": meta_title or Path(urlparse(req.url).path).name or req.url,
        "description": None,
        "status_code": status_code,
        "language": None,
        "source_url": final_url,
        "formats": formats,
        "is_pdf": True,
        "page_count": len(pages_text),
    }
    notes = []
    if not body_md:
        body_md = "*(no extractable text — likely a scanned/image PDF)*"
        notes.append("no extractable text — likely a scanned/image PDF")
    if "markdown" in formats:
        out["markdown"] = body_md
    if "json" in formats:
        structure = markdown_to_structured(body_md)
        log.emit(
            "structure",
            f"parsed pdf text into {_count_sections(structure['sections'])} sections",
        )
        out["json"] = {"title": out["title"], "url": req.url, **structure}
    if "screenshot" in formats:
        out["screenshot_error"] = "screenshots are not supported for PDF documents"
    if any(f in formats for f in ("html", "rawHtml", "links")):
        notes.append("html/rawHtml/links are not available for PDFs")
    if notes:
        out["pdf_note"] = "; ".join(notes)
    return out


async def camoufox_screenshot(
    url: str, wait_for: int | None, timeout: int, log: RunLog
) -> dict[str, Any]:
    payload: dict[str, Any] = {"url": url, "timeout": timeout, "full_page": True}
    if wait_for:
        payload["wait_after_load"] = wait_for
    # The browser service's worst case is goto(timeout) + capture(timeout) +
    # viewport fallback; the global 90s client timeout would abandon requests
    # it is still legitimately working on. Budget the call from the payload.
    call_timeout = httpx.Timeout(timeout / 1000 * 2 + 45, connect=10.0)
    # Navigation time varies a lot on throttled/heavy sites; one retry
    # absorbs most transient goto timeouts.
    last_exc: Exception | None = None
    for attempt in range(1, 3):
        log.emit(
            "screenshot",
            f"rendering full-page screenshot of {url} via {BROWSER_URL}"
            + (f" (retry {attempt - 1})" if attempt > 1 else ""),
        )
        try:
            r = await client.post(f"{BROWSER_URL}/screenshot", json=payload, timeout=call_timeout)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Surface the browser service's own error message, not just the status line.
            try:
                detail = e.response.json().get("error") or e.response.text[:300]
            except Exception:
                detail = e.response.text[:300] or str(e)
            log.emit("screenshot", f"attempt {attempt} failed: {detail}")
            last_exc = HTTPException(
                status_code=502, detail=f"Browser screenshot failed for {url}: {detail}"
            )
            continue
        except httpx.HTTPError as e:
            # str() of httpx timeouts is often empty; include the class name.
            detail = f"{type(e).__name__}: {e}".rstrip(": ")
            log.emit("screenshot", f"attempt {attempt} failed: {detail}")
            last_exc = HTTPException(
                status_code=502, detail=f"Browser screenshot error for {url}: {detail}"
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
            status_code=502, detail=f"Browser service returned no screenshot for {url}"
        )
    if isinstance(last_exc, HTTPException):
        raise last_exc
    raise HTTPException(
        status_code=502, detail=f"Browser screenshot error for {url}: {last_exc}"
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

    if _looks_like_pdf_url(req.url):
        return await fetch_pdf(req, log)

    def attach_json(page: dict[str, Any]) -> dict[str, Any]:
        if not want_json or page.get("is_pdf"):
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
            _scrape_with_pdf_fallback(req, fc_formats, timeout, log),
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

    return attach_json(await _scrape_with_pdf_fallback(req, fc_formats, timeout, log))


async def _scrape_with_pdf_fallback(
    req: FetchRequest, formats: list[str], timeout: int, log: RunLog
) -> dict[str, Any]:
    """Scrape via Firecrawl, falling back to local PDF parsing when the URL
    turns out to serve a PDF (Firecrawl error, empty markdown, or an
    application/pdf content type)."""
    try:
        page = await _firecrawl_request(req, formats, timeout, log)
    except HTTPException:
        pdf = await fetch_pdf(req, log, sniff=True)
        if pdf is not None:
            log.emit("pdf", f"{req.url} turned out to be a pdf — parsed locally")
            return pdf
        raise
    content_type = (page.pop("_content_type", None) or "").lower()
    empty_md = "markdown" in formats and not (page.get("markdown") or "").strip()
    if content_type.startswith("application/pdf") or empty_md:
        pdf = await fetch_pdf(req, log, sniff=True)
        if pdf is not None:
            log.emit("pdf", f"{req.url} turned out to be a pdf — parsed locally")
            return pdf
    return page


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
    try:
        r = await client.post(f"{FIRECRAWL_URL}/v2/scrape", json=payload, headers=FIRECRAWL_HEADERS)
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
    out = _normalize_fc_page(data, formats, url=req.url)
    out["_content_type"] = meta.get("contentType")
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
        r = await client.get(f"{BROWSER_URL}/health", timeout=10)
        status["browser"] = (
            f"ok ({BROWSER_URL})" if r.status_code == 200 else f"http {r.status_code} ({BROWSER_URL})"
        )
    except Exception as e:
        status["browser"] = f"unreachable ({BROWSER_URL}): {e}"
    return status


# ── LLM access via OpenRouter (or any OpenAI-compatible endpoint) ──

async def llm_chat(
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    log: RunLog,
    stage: str = "llm",
    temperature: float | None = None,
    timeout: float = 60.0,
) -> str:
    """Single chokepoint for all chat-completion calls (answer synthesis,
    summarization, navigation). Returns the assistant message content."""
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=400, detail="OPENROUTER_API_KEY not configured — set it in .env")
    body: dict[str, Any] = {"model": ANSWER_MODEL, "max_tokens": max_tokens, "messages": messages}
    if temperature is not None:
        body["temperature"] = temperature
    for attempt in range(2):
        try:
            r = await client.post(
                f"{ANSWER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "http://localhost:8088",
                    "X-Title": "local-search",
                },
                json=body,
                timeout=httpx.Timeout(timeout, connect=10.0),
            )
            # Free-tier models rate-limit aggressively; absorb one 429.
            if r.status_code == 429 and attempt == 0:
                log.emit(stage, f"{ANSWER_MODEL} rate-limited (429) — retrying in 2s")
                await asyncio.sleep(2)
                continue
            r.raise_for_status()
        except httpx.HTTPError as e:
            detail = f"{type(e).__name__}: {e}".rstrip(": ")
            raise HTTPException(status_code=502, detail=f"LLM call failed: {detail}") from e
        payload = r.json()
        # OpenRouter can return {"error": ...} with HTTP 200 on some upstream failures.
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            err = (payload.get("error") or {}).get("message") if isinstance(payload.get("error"), dict) else payload.get("error")
            raise HTTPException(
                status_code=502,
                detail=f"LLM returned no content: {err or 'unexpected response shape'}",
            )
        if not content:
            raise HTTPException(status_code=502, detail="LLM returned empty content")
        return content
    raise HTTPException(status_code=502, detail="LLM call failed: rate-limited (429)")


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Parse a JSON object out of possibly-chatty model output: strict JSON
    first, then a ```json fence, then the greedy outermost {...} span."""
    for candidate in (
        text,
        *(m.group(1) for m in _JSON_FENCE_RE.finditer(text)),
    ):
        try:
            obj = json.loads(candidate.strip())
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, AttributeError):
            pass
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return None


async def synthesize_answer(
    query: str, results: list[dict[str, Any]], mode: str, log: RunLog
) -> dict[str, Any]:
    sources = results[:5] if mode == "basic" else results[:8]
    blocks = []
    for i, r in enumerate(sources, 1):
        text = f"[{i}] {r.get('title')}\nURL: {r.get('url')}\n{r.get('snippet') or ''}"
        if mode == "advanced" and r.get("content"):
            text += "\nExcerpt:\n" + r["content"][:3000]
        blocks.append(text)
    log.emit("answer", f"synthesizing answer from {len(sources)} sources via {ANSWER_MODEL}")
    text = await llm_chat(
        [
            {
                "role": "system",
                "content": "Answer the question using ONLY the numbered sources provided. "
                "Cite sources with [n] after each claim. If the sources are insufficient "
                "to answer, say so plainly.",
            },
            {
                "role": "user",
                "content": f"Question: {query}\n\nSources:\n\n" + "\n\n".join(blocks),
            },
        ],
        max_tokens=700 if mode == "basic" else 1200,
        log=log,
        stage="answer",
    )
    log.emit("answer", f"answer ready ({len(text)} chars)")
    return {"answer": text, "answer_model": ANSWER_MODEL}


# ── Per-page summarization (summarize flag on /fetch and /crawl) ──

# Generous budget: reasoning models (e.g. nemotron) spend tokens thinking
# before the visible summary, and max_tokens covers both.
SUMMARIZE_MAX_TOKENS = 800
SUMMARIZE_INPUT_CHARS = 6000
SUMMARIZE_CONCURRENCY = 3  # below FETCH_BATCH_CONCURRENCY: free-tier rate limits


async def summarize_page(page: dict[str, Any], log: RunLog, goal: str | None = None):
    """Attach page['summary'] in place; on failure attach page['summary_error']
    and never raise (mirrors the screenshot_error/content_error pattern)."""
    url = page.get("url") or "?"
    text = (page.get("markdown") or "").strip()
    if not text:
        page["summary_error"] = "no markdown content to summarize"
        return
    prompt = (
        f"Summarize this page relative to the goal: {goal}" if goal else "Summarize this page."
    )
    try:
        log.emit("summarize", f"summarizing {url} via {ANSWER_MODEL}")
        summary = await llm_chat(
            [
                {
                    "role": "system",
                    "content": "You summarize web pages. Reply with a tight 2-4 sentence "
                    "summary of the page content. No preamble, no markdown headings.",
                },
                {
                    "role": "user",
                    "content": f"{prompt}\n\nPage: {page.get('title') or url}\nURL: {url}\n\n"
                    + text[:SUMMARIZE_INPUT_CHARS],
                },
            ],
            max_tokens=SUMMARIZE_MAX_TOKENS,
            log=log,
            stage="summarize",
        )
        page["summary"] = summary.strip()
        page["summary_model"] = ANSWER_MODEL
        log.emit("summarize", f"summary ready for {url} ({len(page['summary'])} chars)")
    except HTTPException as e:
        page["summary_error"] = str(e.detail)
        log.emit("summarize", f"summary failed for {url}: {e.detail}")
    except Exception as e:
        page["summary_error"] = str(e)
        log.emit("summarize", f"summary failed for {url}: {e}")


async def _summarize_pages(pages: list[dict[str, Any]], log: RunLog, goal: str | None = None):
    if not pages:
        return
    if not OPENROUTER_API_KEY:
        log.emit("summarize", "skipped: no OPENROUTER_API_KEY configured")
        for page in pages:
            page["summary_error"] = "OPENROUTER_API_KEY not configured — set it in .env"
        return
    sem = asyncio.Semaphore(SUMMARIZE_CONCURRENCY)

    async def one(page: dict[str, Any]):
        async with sem:
            await summarize_page(page, log, goal=goal)

    await asyncio.gather(*(one(p) for p in pages))


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

    out: dict[str, Any] = {"query": req.query, "result_count": len(results), "results": results}
    mode = "basic" if req.include_answer is True else req.include_answer
    if mode:  # answer synthesis is best-effort — never fails the search
        if not OPENROUTER_API_KEY:
            out["answer_error"] = "OPENROUTER_API_KEY not configured — set it in .env"
            log.emit("answer", "skipped: no OPENROUTER_API_KEY configured")
        elif not results:
            out["answer_error"] = "no results to answer from"
        else:
            try:
                out.update(await synthesize_answer(req.query, results, mode, log))
            except Exception as e:
                out["answer_error"] = f"answer synthesis failed: {e}"
                log.emit("answer", out["answer_error"])
    return out


def _search_summary(result: dict[str, Any]) -> dict[str, Any]:
    results = result.get("results", [])
    return {
        "result_count": result.get("result_count", 0),
        "scraped": sum(
            1 for r in results if any(k in r for k in ("content", "html", "raw_html", "links", "json", "screenshot"))
        ),
        "scrape_errors": sum(1 for r in results if "content_error" in r),
        "screenshots": sum(1 for r in results if "screenshot" in r),
        "answer": "answer" in result,
        **({"answer_error": result["answer_error"]} if result.get("answer_error") else {}),
    }


def _fetch_summary(page: dict[str, Any]) -> dict[str, Any]:
    if "results" in page:  # batch
        return {
            "batch": True,
            "requested": len(page.get("urls") or []),
            "succeeded": page.get("result_count", 0),
            "failed": page.get("failed_count", 0),
            "markdown_chars": sum(len(p.get("markdown") or "") for p in page["results"]) or None,
            "screenshots": sum(1 for p in page["results"] if "screenshot" in p),
            **_summarize_counts(page["results"]),
        }
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
        **({"pdf_pages": page["page_count"]} if page.get("is_pdf") else {}),
        **_summarize_counts([page]),
    }


def _summarize_counts(pages: list[dict[str, Any]]) -> dict[str, Any]:
    summarized = sum(1 for p in pages if "summary" in p)
    errors = sum(1 for p in pages if "summary_error" in p)
    out: dict[str, Any] = {}
    if summarized:
        out["summarized"] = summarized
    if errors:
        out["summary_errors"] = errors
    return out


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
    include_domains: str | None = None,
    exclude_domains: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    include_answer: str | None = None,
):
    def _split(csv: str | None) -> list[str] | None:
        parts = [p.strip() for p in (csv or "").split(",") if p.strip()]
        return parts or None

    answer: bool | str = False
    if include_answer in ("true", "1", "basic"):
        answer = "basic"
    elif include_answer == "advanced":
        answer = "advanced"

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
        include_domains=_split(include_domains),
        exclude_domains=_split(exclude_domains),
        start_date=start_date,
        end_date=end_date,
        include_answer=answer,
    )
    log = RunLog("search", req.query)
    return await _run_recorded(
        "search", req.query, req.model_dump(), lambda l: _run_search(req, l), _search_summary, log
    )


async def _run_fetch_batch(req: FetchRequest, log: RunLog) -> dict[str, Any]:
    # Screenshot batches lean on camoufox (MAX_CONCURRENT_PAGES=5, doubled
    # under stealth), so back off the fan-out for those.
    concurrency = 3 if "screenshot" in (req.formats or []) else FETCH_BATCH_CONCURRENCY
    sem = asyncio.Semaphore(concurrency)
    slots: list[dict[str, Any] | None] = [None] * len(req.urls)  # preserves input order
    failed: list[dict[str, Any]] = []
    log.emit("fetch", f"batch fetching {len(req.urls)} urls (concurrency {concurrency})")

    async def one(i: int, u: str):
        async with sem:
            sub = req.model_copy(update={"url": u, "urls": None})
            try:
                slots[i] = _apply_max_chars(await firecrawl_scrape(sub, log), req.max_chars)
            except HTTPException as e:
                failed.append({"url": u, "error": str(e.detail)})
                log.emit("fetch", f"failed {u}: {e.detail}")
            except Exception as e:
                failed.append({"url": u, "error": str(e)})
                log.emit("fetch", f"failed {u}: {e}")

    await asyncio.gather(*(one(i, u) for i, u in enumerate(req.urls)))
    results = [p for p in slots if p is not None]
    return {
        "urls": req.urls,
        "result_count": len(results),
        "failed_count": len(failed),
        "results": results,
        "failed_results": failed,
    }


async def _run_fetch(req: FetchRequest, log: RunLog) -> dict[str, Any]:
    formats = list(req.formats) if req.formats else ["markdown"]
    # Summaries are derived from markdown; scrape it internally when the
    # caller didn't ask for it, then strip it back off (same as json).
    strip_md = req.summarize and "markdown" not in formats
    if strip_md:
        req = req.model_copy(update={"formats": formats + ["markdown"]})
    if req.urls:
        result = await _run_fetch_batch(req, log)
        pages = result["results"]
    else:
        result = _apply_max_chars(await firecrawl_scrape(req, log), req.max_chars)
        pages = [result]
    if req.summarize:
        await _summarize_pages(pages, log)
    if strip_md:
        for page in pages:
            for k in ("markdown", "truncated", "truncated_at"):
                page.pop(k, None)
            page["formats"] = formats
    return result


def _fetch_label(req: FetchRequest) -> str:
    return req.url or f"batch: {len(req.urls)} urls"


@app.post("/fetch")
async def fetch(req: FetchRequest):
    label = _fetch_label(req)
    log = RunLog("fetch", label)
    return await _run_recorded(
        "fetch", label, req.model_dump(), lambda l: _run_fetch(req, l), _fetch_summary, log
    )


@app.post("/fetch/stream")
async def fetch_stream(req: FetchRequest):
    label = _fetch_label(req)
    return _stream_response(
        "fetch", label, req.model_dump(), lambda l: _run_fetch(req, l), _fetch_summary
    )


# ── Map: discover a site's URLs via Firecrawl (no scraping) ──

_SITEMAP_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_COMMON_SUBDOMAINS = ["www", "blog", "app", "api", "help", "docs", "support", "news", "m"]


def _root_domain(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


async def _fetch_xml(url: str) -> str | None:
    """Fetch a sitemap URL. Tries direct HTTP first, then Firecrawl rawHtml fallback."""
    headers = {"User-Agent": _SITEMAP_BROWSER_UA, "Accept": "application/xml,text/xml,*/*"}
    try:
        r = await client.get(url, headers=headers, timeout=10, follow_redirects=True)
        if r.status_code == 200:
            ct = r.headers.get("content-type", "")
            text = r.text
            if "xml" in ct or text.lstrip().startswith("<?xml") or "<urlset" in text or "<sitemapindex" in text:
                return text
    except Exception:
        pass
    # Fallback: ask Firecrawl to fetch the raw bytes for us
    try:
        r = await client.post(
            f"{FIRECRAWL_URL}/v2/scrape",
            json={"url": url, "formats": ["rawHtml"]},
            headers=FIRECRAWL_HEADERS,
            timeout=20,
        )
        if r.status_code == 200:
            body = r.json()
            if body.get("success"):
                raw = body.get("data", {}).get("rawHtml", "")
                if "<urlset" in raw or "<sitemapindex" in raw or "<?xml" in raw:
                    return raw
    except Exception:
        pass
    return None


def _parse_sitemap(xml_text: str) -> tuple[list[str], list[str]]:
    """Return (page_urls, child_sitemap_urls). Handles with/without namespace; regex fallback."""
    ns = f"{{{_SITEMAP_NS}}}"
    page_urls: list[str] = []
    sitemap_urls: list[str] = []
    try:
        root = ET.fromstring(xml_text)
        tag = root.tag
        is_index = "sitemapindex" in tag
        # Try namespace-qualified names first, then bare names
        for prefix in (ns, ""):
            sm_tag, url_tag, loc_tag = f"{prefix}sitemap", f"{prefix}url", f"{prefix}loc"
            if is_index:
                items = root.findall(f".//{sm_tag}")
            else:
                items = root.findall(f".//{url_tag}")
            if not items:
                continue
            for el in items:
                loc = el.find(loc_tag)
                if loc is not None and loc.text:
                    if is_index:
                        sitemap_urls.append(loc.text.strip())
                    else:
                        page_urls.append(loc.text.strip())
            break  # found with this prefix, stop
    except ET.ParseError:
        all_locs = re.findall(r"<loc>\s*(https?://[^\s<]+)\s*</loc>", xml_text)
        if re.search(r"<sitemapindex", xml_text, re.I):
            sitemap_urls = all_locs
        else:
            page_urls = all_locs
    return page_urls, sitemap_urls


async def _discover_sitemap_urls(root_url: str, include_subdomains: bool, log: RunLog) -> list[str]:
    """
    Discover URLs by parsing the site's sitemaps.
    1. Check robots.txt for Sitemap: directives.
    2. Try /sitemap.xml and /sitemap_index.xml.
    3. Follow sitemap index entries (max 2 levels deep).
    4. If include_subdomains, also probe sitemaps of discovered and common subdomains.
    """
    origin = _root_domain(root_url)
    parsed = urlparse(root_url)
    # Extract registrable domain (last 2 parts) for subdomain probing
    host_parts = parsed.hostname.split(".") if parsed.hostname else []
    reg_domain = ".".join(host_parts[-2:]) if len(host_parts) >= 2 else parsed.hostname or ""

    # Seed sitemap list from robots.txt then well-known paths
    seed: list[str] = []
    robots_text = None
    try:
        r = await client.get(
            f"{origin}/robots.txt",
            headers={"User-Agent": _SITEMAP_BROWSER_UA},
            timeout=8,
            follow_redirects=True,
        )
        if r.status_code == 200:
            robots_text = r.text
            for line in robots_text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sm_url = line.split(":", 1)[1].strip()
                    if sm_url not in seed:
                        seed.append(sm_url)
    except Exception:
        pass

    for fallback in (f"{origin}/sitemap.xml", f"{origin}/sitemap_index.xml"):
        if fallback not in seed:
            seed.append(fallback)

    all_urls: set[str] = set()
    visited: set[str] = set()

    async def _process_sitemap(sm_url: str, depth: int):
        if sm_url in visited or depth > 2:
            return
        visited.add(sm_url)
        xml_text = await _fetch_xml(sm_url)
        if not xml_text:
            return
        page_urls, child_sms = _parse_sitemap(xml_text)
        all_urls.update(page_urls)
        if depth < 2 and child_sms:
            log.emit("sitemap", f"{sm_url}: index with {len(child_sms)} entries, {len(page_urls)} URLs")
            await asyncio.gather(*[_process_sitemap(c, depth + 1) for c in child_sms])
        else:
            log.emit("sitemap", f"{sm_url}: {len(page_urls)} URLs")

    await asyncio.gather(*[_process_sitemap(s, 0) for s in seed])

    if include_subdomains:
        # Find subdomains already seen in discovered URLs
        seen_hosts: set[str] = set()
        for u in all_urls:
            try:
                h = urlparse(u).hostname or ""
                if h.endswith(f".{reg_domain}") and h != parsed.hostname:
                    seen_hosts.add(h)
            except Exception:
                pass
        # Also probe common subdomains
        for sub in _COMMON_SUBDOMAINS:
            candidate = f"{sub}.{reg_domain}"
            if candidate != parsed.hostname:
                seen_hosts.add(candidate)

        async def _probe_subdomain(host: str):
            sub_origin = f"{parsed.scheme}://{host}"
            for path in ("/robots.txt", "/sitemap.xml", "/sitemap_index.xml"):
                sm_url = f"{sub_origin}{path}"
                if sm_url in visited:
                    continue
                xml_or_robots = await _fetch_xml(sm_url)
                if not xml_or_robots:
                    continue
                if path == "/robots.txt":
                    # Extract sitemap directives
                    for line in xml_or_robots.splitlines():
                        if line.lower().startswith("sitemap:"):
                            sm = line.split(":", 1)[1].strip()
                            await _process_sitemap(sm, 1)
                else:
                    await _process_sitemap(sm_url, 1)
                break  # found something for this subdomain

        if seen_hosts:
            log.emit("sitemap", f"probing {len(seen_hosts)} subdomains")
            await asyncio.gather(*[_probe_subdomain(h) for h in seen_hosts])

    return list(all_urls)


class MapRequest(BaseModel):
    url: str = Field(..., description="Site to map")
    search: str | None = Field(None, description="Filter/rank discovered links by this term")
    limit: int = Field(100, ge=1, le=5000, description="Max URLs to return")
    include_subdomains: bool = Field(True, description="Include links on subdomains")
    ignore_query_parameters: bool = Field(
        True, description="Collapse URLs that differ only by query string"
    )
    sitemap: str = Field(
        "include", pattern="^(skip|include|only)$",
        description="Sitemap usage: 'include' (default), 'skip', or 'only'",
    )
    timeout: int | None = Field(None, description="Upstream map timeout in ms")


async def _firecrawl_map(url: str, payload: dict[str, Any], log: RunLog) -> list[dict[str, Any]]:
    """Call Firecrawl /v2/map and return link objects."""
    try:
        r = await client.post(f"{FIRECRAWL_URL}/v2/map", json=payload, headers=FIRECRAWL_HEADERS)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.emit("map", f"firecrawl map error: {e}")
        raise
    body = r.json()
    if not body.get("success"):
        raise ValueError(f"Firecrawl map failed: {body.get('error')}")
    raw = body.get("links", [])
    return [l if isinstance(l, dict) else {"url": l} for l in raw]


async def _run_map(req: MapRequest, log: RunLog) -> dict[str, Any]:
    # Firecrawl v2 uses ignoreSitemap/sitemapOnly booleans, not a "sitemap" string field
    payload: dict[str, Any] = {
        "url": req.url,
        "limit": req.limit,
        "includeSubdomains": req.include_subdomains,
        "ignoreQueryParameters": req.ignore_query_parameters,
    }
    if req.sitemap == "skip":
        payload["ignoreSitemap"] = True
    elif req.sitemap == "only":
        payload["sitemapOnly"] = True
    # "include" = Firecrawl default (both flags false)
    if req.search:
        payload["search"] = req.search
    if req.timeout:
        payload["timeout"] = req.timeout

    log.emit("map", f"mapping {req.url} (sitemap={req.sitemap}, limit={req.limit})")

    # Run Firecrawl map and independent sitemap discovery in parallel
    fc_task: asyncio.Task = asyncio.create_task(_firecrawl_map(req.url, payload, log))
    sm_task: asyncio.Task | None = None
    if req.sitemap != "skip":
        sm_task = asyncio.create_task(
            _discover_sitemap_urls(req.url, req.include_subdomains, log)
        )

    fc_links: list[dict[str, Any]] = []
    sm_urls: list[str] = []

    try:
        fc_links = await fc_task
        log.emit("map", f"firecrawl: {len(fc_links)} links")
    except Exception as e:
        log.emit("map", f"firecrawl map failed ({e}), relying on sitemap discovery")

    if sm_task is not None:
        try:
            sm_urls = await sm_task
            log.emit("sitemap", f"sitemap discovery: {len(sm_urls)} URLs")
        except Exception as e:
            log.emit("sitemap", f"sitemap discovery error: {e}")

    if not fc_links and not sm_urls:
        raise HTTPException(status_code=502, detail=f"Map failed for {req.url}: no sources returned results")

    # Merge: Firecrawl results first, then unique sitemap URLs
    seen: set[str] = {l["url"] for l in fc_links}
    merged = list(fc_links)
    for u in sm_urls:
        if u not in seen:
            seen.add(u)
            merged.append({"url": u})

    # If ignoring query params, collapse duplicates
    if req.ignore_query_parameters:
        deduped: list[dict[str, Any]] = []
        seen_stripped: set[str] = set()
        for link in merged:
            stripped = urlparse(link["url"])._replace(query="", fragment="").geturl()
            if stripped not in seen_stripped:
                seen_stripped.add(stripped)
                deduped.append(link)
        merged = deduped

    merged = merged[: req.limit]
    log.emit("map", f"discovered {len(merged)} links total")
    return {"url": req.url, "link_count": len(merged), "links": merged}


def _map_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {"link_count": result.get("link_count", 0)}


@app.post("/map")
async def map_site(req: MapRequest):
    log = RunLog("map", req.url)
    return await _run_recorded(
        "map", req.url, req.model_dump(), lambda l: _run_map(req, l), _map_summary, log
    )


@app.post("/map/stream")
async def map_stream(req: MapRequest):
    return _stream_response(
        "map", req.url, req.model_dump(), lambda l: _run_map(req, l), _map_summary
    )


# ── Crawl: sync facade over Firecrawl's async crawl job API ──

class CrawlRequest(BaseModel):
    url: str = Field(..., description="Root URL to crawl from")
    limit: int = Field(
        25, ge=1, le=CRAWL_MAX_LIMIT, description=f"Max pages (hard cap {CRAWL_MAX_LIMIT})"
    )
    max_depth: int | None = Field(None, ge=0, description="Max discovery depth from the root URL")
    include_paths: list[str] | None = Field(None, description="Regex patterns of URL paths to crawl")
    exclude_paths: list[str] | None = Field(None, description="Regex patterns of URL paths to skip")
    crawl_entire_domain: bool = Field(
        False, description="Follow sibling/parent URLs, not just child paths"
    )
    allow_subdomains: bool = Field(False, description="Follow links onto subdomains")
    allow_external_links: bool = Field(False, description="Follow links to other domains")
    ignore_query_parameters: bool = Field(
        True, description="Don't re-scrape the same path with different query strings"
    )
    sitemap: str = Field(
        "include", pattern="^(skip|include|only)$",
        description="Sitemap usage: 'include' (default), 'skip', or 'only'",
    )
    delay: float | None = Field(None, ge=0, description="Seconds between page scrapes")
    formats: list[str] = Field(
        ["markdown"],
        description="Per-page formats: markdown/html/rawHtml/links/json (screenshots unsupported)",
    )
    only_main_content: bool = Field(True, description="Strip nav/footer boilerplate")
    max_chars: int | None = Field(None, description="Per-page markdown truncation")
    timeout_s: int = Field(300, ge=30, le=900, description="Overall crawl budget in seconds")
    summarize: bool = Field(
        False,
        description="Attach an LLM-generated summary to each crawled page (requires OPENROUTER_API_KEY)",
    )


CRAWL_POLL_INTERVAL = 2.0
CRAWL_POLL_TIMEOUT = httpx.Timeout(15.0, connect=10.0)


def _firecrawl_local_url(reported: str) -> str:
    """Rewrite a Firecrawl self-reported URL onto FIRECRAWL_URL — the
    self-hosted image reports a base origin that may not resolve from
    this container."""
    p = urlparse(reported)
    return f"{FIRECRAWL_URL}{p.path}" + (f"?{p.query}" if p.query else "")


async def _run_crawl(req: CrawlRequest, log: RunLog) -> dict[str, Any]:
    formats = list(req.formats) if req.formats else ["markdown"]
    if "screenshot" in formats:
        raise HTTPException(
            status_code=400,
            detail="screenshots are not supported for crawls — fetch individual pages instead",
        )
    bad = [f for f in formats if f not in SUPPORTED_FORMATS]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format(s): {bad}. Supported: {sorted(SUPPORTED_FORMATS - {'screenshot'})}",
        )
    want_json = "json" in formats
    # json and summaries are derived from markdown server-side, so ensure
    # markdown is scraped whenever either is requested.
    fc_formats = [f for f in formats if f != "json"]
    if (want_json or req.summarize) and "markdown" not in fc_formats:
        fc_formats.append("markdown")

    payload: dict[str, Any] = {
        "url": req.url,
        "limit": req.limit,
        "sitemap": req.sitemap,
        "ignoreQueryParameters": req.ignore_query_parameters,
        "crawlEntireDomain": req.crawl_entire_domain,
        "allowSubdomains": req.allow_subdomains,
        "allowExternalLinks": req.allow_external_links,
        "scrapeOptions": {"formats": fc_formats, "onlyMainContent": req.only_main_content},
    }
    if req.max_depth is not None:
        payload["maxDiscoveryDepth"] = req.max_depth
    if req.include_paths:
        payload["includePaths"] = req.include_paths
    if req.exclude_paths:
        payload["excludePaths"] = req.exclude_paths
    if req.delay is not None:
        payload["delay"] = req.delay

    t0 = time.monotonic()
    try:
        r = await client.post(
            f"{FIRECRAWL_URL}/v2/crawl", json=payload,
            headers=FIRECRAWL_HEADERS, timeout=CRAWL_POLL_TIMEOUT,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Firecrawl crawl error for {req.url}: {e}") from e
    body = r.json()
    job_id = body.get("id")
    if not body.get("success") or not job_id:
        raise HTTPException(
            status_code=502, detail=f"Firecrawl crawl failed to start for {req.url}: {body.get('error')}"
        )
    log.emit("crawl", f"started crawl job {job_id} (limit {req.limit})")

    status: dict[str, Any] = {}
    state = "scraping"
    last_progress: tuple[Any, Any] | None = None
    timed_out = False
    while True:
        if time.monotonic() - t0 >= req.timeout_s:
            timed_out = True
            break
        try:
            s = await client.get(
                f"{FIRECRAWL_URL}/v2/crawl/{job_id}",
                headers=FIRECRAWL_HEADERS, timeout=CRAWL_POLL_TIMEOUT,
            )
            s.raise_for_status()
            status = s.json()
        except httpx.HTTPError as e:
            log.emit("crawl", f"poll failed (will retry): {e}")
            await asyncio.sleep(CRAWL_POLL_INTERVAL)
            continue
        state = status.get("status", "scraping")
        progress = (status.get("completed", 0), state)
        if progress != last_progress:
            log.emit("crawl", f"{status.get('completed', 0)}/{status.get('total', '?')} pages ({state})")
            last_progress = progress
        if state in ("completed", "failed", "cancelled"):
            break
        await asyncio.sleep(CRAWL_POLL_INTERVAL)

    if timed_out:
        log.emit("crawl", f"crawl budget of {req.timeout_s}s exhausted — cancelling job")
        try:
            await client.delete(
                f"{FIRECRAWL_URL}/v2/crawl/{job_id}",
                headers=FIRECRAWL_HEADERS, timeout=CRAWL_POLL_TIMEOUT,
            )
        except httpx.HTTPError:
            pass

    # Collect pages (follow pagination on completed crawls).
    raw_pages: list[dict[str, Any]] = list(status.get("data") or [])
    next_url = status.get("next") if state == "completed" else None
    while next_url:
        try:
            s = await client.get(
                _firecrawl_local_url(next_url), headers=FIRECRAWL_HEADERS, timeout=CRAWL_POLL_TIMEOUT
            )
            s.raise_for_status()
        except httpx.HTTPError as e:
            log.emit("crawl", f"pagination fetch failed, returning partial pages: {e}")
            break
        chunk = s.json()
        raw_pages.extend(chunk.get("data") or [])
        next_url = chunk.get("next")

    final_status = "completed" if state == "completed" else ("timeout" if timed_out else "failed")
    error = status.get("error")
    if final_status != "completed" and not raw_pages:
        raise HTTPException(
            status_code=502,
            detail=f"Crawl {final_status} for {req.url} with no pages"
            + (f": {error}" if error else ""),
        )

    pages = []
    for data in raw_pages:
        page = _normalize_fc_page(data, formats)
        if want_json:
            structure = markdown_to_structured(data.get("markdown") or "")
            page["json"] = {"title": page.get("title"), "url": page.get("url"), **structure}
            if "markdown" not in formats:
                page.pop("markdown", None)
        pages.append(_apply_max_chars(page, req.max_chars))
    if want_json:
        log.emit("structure", f"derived structured json for {len(pages)} pages")
    log.emit("crawl", f"crawl {final_status}: {len(pages)} pages")

    if req.summarize and pages:
        strip_md = "markdown" not in formats
        if strip_md:
            for page, data in zip(pages, raw_pages):
                page["markdown"] = data.get("markdown")
        log.emit("summarize", f"summarizing {len(pages)} pages (concurrency {SUMMARIZE_CONCURRENCY})")
        await _summarize_pages(pages, log)
        if strip_md:
            for page in pages:
                page.pop("markdown", None)

    return {
        "url": req.url,
        "job_id": job_id,
        "status": final_status,
        "partial": final_status != "completed",
        "total": status.get("total"),
        "page_count": len(pages),
        "formats": formats,
        "pages": pages,
        **({"error": error} if error else {}),
    }


def _crawl_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "page_count": result.get("page_count", 0),
        "total": result.get("total"),
        "formats": result.get("formats"),
        **_summarize_counts(result.get("pages") or []),
    }


@app.post("/crawl")
async def crawl_site(req: CrawlRequest):
    log = RunLog("crawl", req.url)
    return await _run_recorded(
        "crawl", req.url, req.model_dump(), lambda l: _run_crawl(req, l), _crawl_summary, log
    )


@app.post("/crawl/stream")
async def crawl_stream(req: CrawlRequest):
    return _stream_response(
        "crawl", req.url, req.model_dump(), lambda l: _run_crawl(req, l), _crawl_summary
    )


# ── Navigate: LLM-guided goal-directed walk through a website ──

NAVIGATE_MAX_STEPS_CAP = 15
NAVIGATE_DEFAULT_STEPS = 6
NAVIGATE_LINKS_SHOWN = 40
NAVIGATE_PAGE_CHARS = 6000
NAVIGATE_FINDINGS_CHARS = 4000


class NavigateRequest(BaseModel):
    url: str = Field(..., description="Starting URL for the walk")
    goal: str = Field(
        ..., description="Natural-language goal, e.g. 'find the pricing of the team plan'"
    )
    max_steps: int = Field(
        NAVIGATE_DEFAULT_STEPS, ge=1, le=NAVIGATE_MAX_STEPS_CAP,
        description=f"Max pages to visit (hard cap {NAVIGATE_MAX_STEPS_CAP})",
    )
    allow_subdomains: bool = Field(True, description="Follow links onto sibling subdomains")
    allow_external_links: bool = Field(False, description="Follow links to other domains")
    stealth: bool = Field(False, description="Render pages through the anti-detect browser")
    only_main_content: bool = Field(True, description="Strip nav/footer boilerplate")
    max_chars: int | None = Field(
        None, description=f"Per-page content budget shown to the LLM (default {NAVIGATE_PAGE_CHARS})"
    )
    timeout_s: int = Field(300, ge=30, le=900, description="Overall navigation budget in seconds")


def _canon(url: str) -> str:
    """Normalize a URL for visited-set dedup: drop fragment, trailing slash."""
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return p._replace(fragment="", path=path).geturl()


def _in_scope(candidate: str, root_host: str, allow_sub: bool, allow_ext: bool) -> bool:
    p = urlparse(candidate)
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower()
    if not host:
        return False
    if allow_ext:
        return True
    root = root_host.lower()
    strip = lambda h: h[4:] if h.startswith("www.") else h  # noqa: E731
    if strip(host) == strip(root):
        return True
    if allow_sub:
        # Same registrable domain (last two labels) covers docs.x.com ↔ www.x.com.
        parts = strip(root).split(".")
        reg = ".".join(parts[-2:]) if len(parts) >= 2 else strip(root)
        return host == reg or host.endswith("." + reg)
    return False


def _nav_candidates(
    links: list[Any] | None, visited: set[str], root_host: str,
    req: NavigateRequest, base: str,
) -> list[str]:
    """Filter page links to in-scope, unvisited http(s) URLs the model may follow."""
    out: list[str] = []
    seen: set[str] = set()
    for link in links or []:
        raw = link.get("url") if isinstance(link, dict) else link
        if not raw or not isinstance(raw, str):
            continue
        url = urljoin(base, raw.strip())
        c = _canon(url)
        if c in visited or c in seen:
            continue
        if not _in_scope(url, root_host, req.allow_subdomains, req.allow_external_links):
            continue
        seen.add(c)
        out.append(url)
        if len(out) >= NAVIGATE_LINKS_SHOWN:
            break
    return out


_NAVIGATE_SYSTEM = (
    "You are navigating a website step by step toward a goal. Each step you see the "
    "current page's content and a numbered list of candidate links you may follow next. "
    "Respond with ONLY a JSON object, no other text:\n"
    '{"findings": "facts from THIS page relevant to the goal, or empty string", '
    '"relevant": true|false, '
    '"goal_met": true|false, '
    '"answer": "complete answer to the goal if goal_met, else null", '
    '"next_url": "one URL copied verbatim from the candidate list, or null if none looks promising", '
    '"reason": "one short sentence explaining your choice"}\n'
    "Rules: next_url MUST be copied exactly from the candidate list — never invent URLs. "
    "Set goal_met true only when the accumulated findings fully answer the goal."
)


async def _navigate_step_decision(
    req: NavigateRequest, step: int, page: dict[str, Any],
    candidates: list[str], findings: list[str], log: RunLog,
) -> dict[str, Any]:
    md = (page.get("markdown") or "").strip()[: req.max_chars or NAVIGATE_PAGE_CHARS]
    found = "\n\n".join(findings)[-NAVIGATE_FINDINGS_CHARS:] if findings else "(none yet)"
    cand_block = (
        "\n".join(f"{i}. {u}" for i, u in enumerate(candidates, 1))
        if candidates else "(no in-scope unvisited links on this page)"
    )
    user = (
        f"Goal: {req.goal}\n\n"
        f"Findings so far:\n{found}\n\n"
        f"Current page (step {step}/{req.max_steps}): "
        f"{page.get('title') or '(untitled)'} — {page.get('url')}\n"
        f"---\n{md or '(no extractable content)'}\n---\n\n"
        f"Candidate links:\n{cand_block}"
    )
    log.emit("navigate", f"asking {ANSWER_MODEL} to assess page and pick the next link")
    raw = await llm_chat(
        [{"role": "system", "content": _NAVIGATE_SYSTEM}, {"role": "user", "content": user}],
        max_tokens=2000, log=log, stage="navigate", timeout=180.0,
    )
    decision = _extract_json(raw)
    if decision is None:
        log.emit("navigate", "model reply was not parseable JSON — treating as no-op step")
        return {}
    return decision


async def _navigate_synthesize(goal: str, findings: list[str], log: RunLog) -> str | None:
    if not findings:
        return None
    log.emit("navigate", f"synthesizing final answer from {len(findings)} page findings")
    try:
        text = await llm_chat(
            [
                {
                    "role": "system",
                    "content": "Answer the goal using ONLY the findings provided. Each finding "
                    "is tagged with its source [url]; cite those URLs after each claim. If the "
                    "findings are insufficient, summarize what was learned and say what's missing.",
                },
                {
                    "role": "user",
                    "content": f"Goal: {goal}\n\nFindings:\n\n" + "\n\n".join(findings),
                },
            ],
            max_tokens=1500, log=log, stage="navigate", timeout=180.0,
        )
        return text.strip()
    except HTTPException as e:
        log.emit("navigate", f"final synthesis failed: {e.detail}")
        return None


async def _run_navigate(req: NavigateRequest, log: RunLog) -> dict[str, Any]:
    # The LLM is the core of this endpoint — hard-fail without a key.
    if not OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=400, detail="/navigate requires OPENROUTER_API_KEY — set it in .env"
        )
    root_host = (urlparse(req.url).hostname or "").lower()
    if not root_host:
        raise HTTPException(status_code=400, detail=f"Invalid start URL: {req.url}")

    t0 = time.monotonic()
    visited: set[str] = set()
    trail: list[dict[str, Any]] = []
    findings: list[str] = []
    status = "exhausted"
    answer: str | None = None
    current = req.url

    for step in range(1, req.max_steps + 1):
        if time.monotonic() - t0 >= req.timeout_s:
            log.emit("navigate", f"time budget of {req.timeout_s}s exhausted before step {step}")
            break
        log.emit("navigate", f"step {step}/{req.max_steps}: scraping {current}")
        visited.add(_canon(current))
        sub = FetchRequest(
            url=current, formats=["markdown", "links"],
            only_main_content=req.only_main_content, stealth=req.stealth,
        )
        try:
            page = await firecrawl_scrape(sub, log)
        except HTTPException as e:
            if not trail:
                raise  # nothing accumulated — surface the scrape error directly
            log.emit("navigate", f"scrape failed at step {step} — ending walk: {e.detail}")
            trail.append({"url": current, "title": None, "step": step,
                          "relevant": False, "summary": None, "error": str(e.detail)})
            break

        candidates = _nav_candidates(page.get("links"), visited, root_host, req, base=current)
        try:
            decision = await _navigate_step_decision(req, step, page, candidates, findings, log)
        except HTTPException as e:
            log.emit("navigate", f"LLM failed at step {step} — ending walk: {e.detail}")
            trail.append({"url": current, "title": page.get("title"), "step": step,
                          "relevant": False, "summary": None, "error": str(e.detail)})
            if not findings:
                raise
            break

        page_findings = str(decision.get("findings") or "").strip()
        relevant = bool(decision.get("relevant"))
        trail.append({"url": current, "title": page.get("title"), "step": step,
                      "relevant": relevant, "summary": page_findings or None})
        if page_findings:
            findings.append(f"[{current}] {page_findings}")

        if decision.get("goal_met"):
            answer = str(decision.get("answer") or "").strip() or None
            status = "achieved"
            log.emit("navigate", f"goal achieved at step {step}")
            break

        next_url = str(decision.get("next_url") or "").strip()
        chosen = None
        if next_url:
            nc = _canon(urljoin(current, next_url))
            chosen = next((c for c in candidates if _canon(c) == nc), None)
        if chosen is None:
            if next_url:
                log.emit("navigate", f"model proposed a URL outside the candidate list ({next_url}) — stopping")
            else:
                log.emit("navigate", "no promising link to follow — stopping")
            status = "dead_end"
            break
        reason = str(decision.get("reason") or "").strip()
        log.emit("navigate", f"goal not yet met; following {chosen}" + (f" — {reason}" if reason else ""))
        current = chosen
    else:
        log.emit("navigate", f"max_steps={req.max_steps} reached without meeting the goal")

    if answer is None:
        answer = await _navigate_synthesize(req.goal, findings, log)

    return {
        "url": req.url,
        "goal": req.goal,
        "status": status,
        "steps": len(trail),
        "answer": answer,
        "answer_model": ANSWER_MODEL,
        "pages": trail,
    }


def _navigate_summary(result: dict[str, Any]) -> dict[str, Any]:
    pages = result.get("pages") or []
    return {
        "status": result.get("status"),
        "steps": result.get("steps", 0),
        "relevant_pages": sum(1 for p in pages if p.get("relevant")),
        "answer": bool(result.get("answer")),
    }


def _navigate_label(req: NavigateRequest) -> str:
    return f"{req.goal} @ {req.url}"


@app.post("/navigate")
async def navigate_site(req: NavigateRequest):
    label = _navigate_label(req)
    log = RunLog("navigate", label)
    return await _run_recorded(
        "navigate", label, req.model_dump(), lambda l: _run_navigate(req, l), _navigate_summary, log
    )


@app.post("/navigate/stream")
async def navigate_stream(req: NavigateRequest):
    label = _navigate_label(req)
    return _stream_response(
        "navigate", label, req.model_dump(), lambda l: _run_navigate(req, l), _navigate_summary
    )
