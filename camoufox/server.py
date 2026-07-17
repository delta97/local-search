"""Camoufox scrape microservice.

Implements the same /scrape contract as Firecrawl's playwright-service, so
Firecrawl can use Camoufox (anti-detect Firefox) as its browser rendering
engine. Request: {url, wait_after_load, timeout, headers, check_selector}.
Response: {content, pageStatusCode, contentType?, pageError?}.
"""

import asyncio
import os
from contextlib import asynccontextmanager

from camoufox.async_api import AsyncCamoufox
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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


@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    async with semaphore:
        page = None
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
            return JSONResponse(body)
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": f"An error occurred while fetching the page: {e}"},
            )
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
