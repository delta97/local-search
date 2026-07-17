"""Camoufox scrape microservice.

Implements the same /scrape contract as Firecrawl's playwright-service, so
Firecrawl can use Camoufox (anti-detect Firefox) as its browser rendering
engine. Request: {url, wait_after_load, timeout, headers, check_selector}.
Response: {content, pageStatusCode, contentType?, pageError?}.

Also exposes /screenshot (called directly by the gateway, not through
Firecrawl, whose playwright-service contract cannot carry images):
{url, wait_after_load, timeout, full_page} -> {screenshot: base64 PNG,
pageStatusCode, title}.
"""

import asyncio
import base64
import logging
import os
import time
from contextlib import asynccontextmanager

from camoufox.async_api import AsyncCamoufox
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
logger = logging.getLogger("camoufox")

HEADLESS_MODE = os.environ.get("CAMOUFOX_HEADLESS", "virtual")  # 'virtual' uses Xvfb (stealthier)
MAX_CONCURRENT_PAGES = int(os.environ.get("MAX_CONCURRENT_PAGES", "5"))

camoufox_cm = None
browser = None
semaphore = asyncio.Semaphore(MAX_CONCURRENT_PAGES)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global camoufox_cm, browser
    headless = True if HEADLESS_MODE == "true" else HEADLESS_MODE
    camoufox_cm = AsyncCamoufox(headless=headless)
    browser = await camoufox_cm.__aenter__()
    yield
    await camoufox_cm.__aexit__(None, None, None)


app = FastAPI(title="camoufox-service", lifespan=lifespan)


class ScreenshotRequest(BaseModel):
    url: str
    wait_after_load: int = Field(1000, description="ms to let the page settle before capture")
    timeout: int = Field(60000, description="navigation timeout in ms")
    full_page: bool = Field(True, description="capture the entire page, not just the viewport")


class ScrapeRequest(BaseModel):
    url: str
    wait_after_load: int = Field(0, description="ms to wait after load")
    timeout: int = Field(15000, description="navigation timeout in ms")
    headers: dict[str, str] | None = None
    check_selector: str | None = None
    skip_tls_verification: bool = False  # accepted for contract parity; TLS handled at launch


@app.get("/health")
async def health():
    return {"status": "ok", "browser": browser is not None, "headless": HEADLESS_MODE}


@app.post("/screenshot")
async def screenshot(req: ScreenshotRequest):
    async with semaphore:
        page = None
        t0 = time.monotonic()
        logger.info(
            "screenshot start url=%s full_page=%s timeout=%dms",
            req.url, req.full_page, req.timeout,
        )
        try:
            page = await browser.new_page()
            # domcontentloaded, not load: the load event can hang past the
            # timeout on tracker/ad requests, and a settle delay after DOM
            # ready is enough for a visual capture.
            response = None
            try:
                response = await page.goto(
                    req.url, wait_until="domcontentloaded", timeout=req.timeout
                )
            except PlaywrightTimeoutError:
                # about:blank means navigation never committed — a real failure.
                # Otherwise the event just never fired (hung trackers, slow
                # subresources); capture whatever has rendered.
                if page.url == "about:blank":
                    raise
                logger.warning(
                    "screenshot goto timed out after %dms but DOM committed url=%s; capturing anyway",
                    req.timeout, req.url,
                )
            if req.wait_after_load > 0:
                await page.wait_for_timeout(req.wait_after_load)
            degraded = False
            try:
                # Explicit timeout: page.screenshot defaults to 30s internally,
                # which full-page captures of very tall pages can exceed even
                # when the caller allowed a longer overall budget.
                img = await page.screenshot(
                    full_page=req.full_page, type="png", timeout=req.timeout
                )
            except Exception as cap_err:
                if not req.full_page:
                    raise
                # Full-page capture fails on very tall/heavy pages (Firefox
                # surface-size limits, capture timeout under memory pressure).
                # A viewport shot is better than a 500.
                logger.warning(
                    "full-page capture failed url=%s (%s: %s); retrying viewport-only",
                    req.url, type(cap_err).__name__, cap_err,
                )
                # Viewport capture is cheap — if the page is so wedged that even
                # this times out, fail fast instead of burning another full budget.
                img = await page.screenshot(
                    full_page=False, type="png", timeout=min(req.timeout, 15000)
                )
                degraded = True
            body = {
                "screenshot": base64.b64encode(img).decode(),
                "pageStatusCode": response.status if response else 200,
                "title": await page.title(),
            }
            if degraded:
                body["degraded"] = "full-page capture failed; captured viewport only"
            logger.info(
                "screenshot ok url=%s bytes=%d elapsed=%.1fs%s",
                req.url, len(img), time.monotonic() - t0,
                " (viewport fallback)" if degraded else "",
            )
            return JSONResponse(body)
        except Exception as e:
            logger.exception(
                "screenshot failed url=%s elapsed=%.1fs", req.url, time.monotonic() - t0
            )
            return JSONResponse(
                status_code=500,
                content={"error": f"Screenshot failed: {type(e).__name__}: {e}"},
            )
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass


@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    async with semaphore:
        page = None
        t0 = time.monotonic()
        logger.info("scrape start url=%s timeout=%dms", req.url, req.timeout)
        try:
            page = await browser.new_page()

            if req.headers:
                # Drop user-agent/cookie-alikes that would clash with Camoufox's
                # generated fingerprint; forward the rest.
                filtered = {
                    k: v for k, v in req.headers.items() if k.lower() != "user-agent"
                }
                if filtered:
                    await page.set_extra_http_headers(filtered)

            response = await page.goto(req.url, wait_until="load", timeout=req.timeout)

            if req.wait_after_load > 0:
                await page.wait_for_timeout(req.wait_after_load)

            if req.check_selector:
                await page.wait_for_selector(req.check_selector, timeout=req.timeout)

            content = await page.content()
            status = response.status if response else 200
            content_type = (response.headers.get("content-type") if response else None) or ""

            body = {
                "content": content,
                "pageStatusCode": status,
                "contentType": content_type,
            }
            if status != 200:
                body["pageError"] = f"HTTP {status}"
            logger.info(
                "scrape ok url=%s status=%d bytes=%d elapsed=%.1fs",
                req.url, status, len(content), time.monotonic() - t0,
            )
            return JSONResponse(body)
        except Exception as e:
            logger.exception(
                "scrape failed url=%s elapsed=%.1fs", req.url, time.monotonic() - t0
            )
            return JSONResponse(
                status_code=500,
                content={"error": f"An error occurred while fetching the page: {type(e).__name__}: {e}"},
            )
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
