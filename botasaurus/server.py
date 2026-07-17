"""Botasaurus scrape microservice.

Implements the same /scrape contract as Firecrawl's playwright-service (and
the camoufox service), so Firecrawl can use Botasaurus (anti-detect Chrome)
as its browser rendering engine. Request: {url, wait_after_load, timeout,
headers, check_selector, bypass_cloudflare?}. Response: {content,
pageStatusCode, contentType?, pageError?}.

Also exposes /screenshot (called directly by the gateway, not through
Firecrawl, whose playwright-service contract cannot carry images):
{url, wait_after_load, timeout, full_page, bypass_cloudflare?} ->
{screenshot: base64 PNG, pageStatusCode, title}.

Unlike camoufox (one shared Firefox, a Playwright page per request), the
botasaurus Driver is synchronous and owns a whole Chrome process, so this
service keeps a pool of pre-launched drivers and runs requests on a thread
pool. A driver that throws is closed and replaced lazily on next checkout.
"""

import asyncio
import logging
import os
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from botasaurus_driver import Driver, cdp
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
logger = logging.getLogger("botasaurus")

HEADLESS_MODE = os.environ.get("BOTASAURUS_HEADLESS", "virtual")  # 'virtual' uses Xvfb (stealthier)
# Each pooled driver is a full Chrome process (~300-500 MB), unlike camoufox's
# pages-in-one-browser, so the default is lower; raising it needs more memory.
MAX_CONCURRENT_PAGES = int(os.environ.get("MAX_CONCURRENT_PAGES", "3"))
CHROME_EXECUTABLE_PATH = os.environ.get("CHROME_EXECUTABLE_PATH")

CHROME_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-setuid-sandbox",
    "--disable-gpu",
    # TLS handled at launch, mirroring camoufox's skip_tls_verification no-op.
    "--ignore-certificate-errors",
]

# Pool slots: a Driver, or None meaning "create a fresh one at checkout"
# (used after a failure so a bad driver never poisons the pool, and pool
# capacity never shrinks even if replacement itself fails).
pool: "queue.Queue[Driver | None]" = queue.Queue()
executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_PAGES)
browser_ready = False


def new_driver() -> Driver:
    global browser_ready
    driver = Driver(
        headless=HEADLESS_MODE == "true",
        enable_xvfb_virtual_display=HEADLESS_MODE == "virtual",
        chrome_executable_path=CHROME_EXECUTABLE_PATH,
        arguments=CHROME_ARGS,
        wait_for_complete_page_load=True,
    )
    browser_ready = True
    return driver


def _is_dead_driver_error(exc: Exception) -> bool:
    # A pooled driver's Chrome can die/disconnect while idle; the first request
    # to reuse it fails in the CDP layer. Distinguishable from legitimate
    # navigation/selector failures so we only retry the former.
    msg = str(exc).lower()
    return "connection refused" in msg or "errno 111" in msg or "connection failure" in msg


def run_on_driver(work):
    """Check a driver out of the pool, run `work(driver)`, return it.

    A driver that throws is always discarded (state is unknown after a
    failure and the thread may still be blocked in a dead Chrome). If a
    *reused* driver dies while idle, retry once on a fresh driver so callers
    don't see a spurious 500; a fresh driver that fails is a real error.
    """
    driver = pool.get()
    reused = driver is not None
    # Exactly one item is returned to the pool per checkout (a driver on
    # success, a lazy None slot on failure) so capacity stays constant.
    for attempt in (1, 2):
        if driver is None:
            try:
                driver = new_driver()
            except Exception:
                pool.put(None)
                raise
            reused = False
        try:
            result = work(driver)
        except Exception as exc:
            try:
                driver.close()
            except Exception:
                pass
            driver = None
            if attempt == 1 and reused and _is_dead_driver_error(exc):
                logger.warning("pooled driver was dead (%s); retrying on a fresh one", exc)
                continue
            pool.put(None)
            raise
        else:
            pool.put(driver)
            return result


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()

    # Warm sequentially, not concurrently: launching multiple Chrome instances
    # at once races on profile dirs / debug ports and can leave a driver with a
    # dead connection. A None slot means "create lazily on first checkout".
    def warm_all() -> list["Driver | None"]:
        out: list[Driver | None] = []
        for _ in range(MAX_CONCURRENT_PAGES):
            try:
                out.append(new_driver())
            except Exception:
                logger.exception("driver warm-up failed; slot will retry lazily")
                out.append(None)
        return out

    drivers = await loop.run_in_executor(executor, warm_all)
    for d in drivers:
        pool.put(d)
    logger.info(
        "driver pool ready: %d/%d launched (headless=%s)",
        sum(1 for d in drivers if d), MAX_CONCURRENT_PAGES, HEADLESS_MODE,
    )
    yield
    while True:
        try:
            d = pool.get_nowait()
        except queue.Empty:
            break
        if d is not None:
            try:
                d.close()
            except Exception:
                pass
    executor.shutdown(wait=False)


app = FastAPI(title="botasaurus-service", lifespan=lifespan)


class ScreenshotRequest(BaseModel):
    url: str
    wait_after_load: int = Field(1000, description="ms to let the page settle before capture")
    timeout: int = Field(60000, description="navigation timeout in ms")
    full_page: bool = Field(True, description="capture the entire page, not just the viewport")
    bypass_cloudflare: bool = Field(False, description="attempt Cloudflare challenge bypass")


class ScrapeRequest(BaseModel):
    url: str
    wait_after_load: int = Field(0, description="ms to wait after load")
    timeout: int = Field(15000, description="navigation timeout in ms")
    headers: dict[str, str] | None = None
    check_selector: str | None = None
    skip_tls_verification: bool = False  # accepted for contract parity; TLS handled at launch
    bypass_cloudflare: bool = Field(False, description="attempt Cloudflare challenge bypass")


# The Chrome-side response object isn't exposed by the botasaurus driver, so
# read the main document's status from navigation timing (Chrome 109+; 0 when
# unavailable -> assume 200). Isolated here so a CDP Network.responseReceived
# listener can replace it without touching the endpoints.
_RESPONSE_META_JS = """
const nav = performance.getEntriesByType('navigation')[0];
return {
    status: (nav && nav.responseStatus) || 0,
    contentType: document.contentType || "",
};
"""


def get_response_meta(driver: Driver) -> tuple[int, str]:
    try:
        meta = driver.run_js(_RESPONSE_META_JS) or {}
        status = int(meta.get("status") or 0) or 200
        return status, meta.get("contentType") or ""
    except Exception:
        return 200, ""


def apply_headers(driver: Driver, headers: "dict[str, str] | None") -> None:
    # Drop user-agent/cookie-alikes that would clash with the driver's own
    # fingerprint; forward the rest. Always set (even empty) because pooled
    # Chromes persist extra headers across requests.
    filtered = {
        k: v for k, v in (headers or {}).items() if k.lower() != "user-agent"
    }
    driver.run_cdp_command(cdp.network.enable())
    driver.run_cdp_command(
        cdp.network.set_extra_http_headers(headers=cdp.network.Headers(filtered))
    )


def navigate(driver: Driver, url: str, timeout_ms: int, bypass_cloudflare: bool) -> None:
    driver.get(
        url,
        bypass_cloudflare=bypass_cloudflare,
        timeout=max(1, timeout_ms // 1000),
    )


def _screenshot_sync(req: ScreenshotRequest) -> dict:
    def work(driver: Driver) -> dict:
        apply_headers(driver, None)
        try:
            navigate(driver, req.url, req.timeout, req.bypass_cloudflare)
        except TimeoutError:
            # Document never reached readyState 'complete' (hung trackers,
            # slow subresources). If navigation never committed it's a real
            # failure; otherwise capture whatever has rendered.
            current = driver.current_url or ""
            if not current or current.startswith(("about:", "chrome-error:")):
                raise
            logger.warning(
                "screenshot goto timed out after %dms but DOM committed url=%s; capturing anyway",
                req.timeout, req.url,
            )
        if req.wait_after_load > 0:
            time.sleep(req.wait_after_load / 1000)
        degraded = False
        try:
            img_b64 = driver.run_cdp_command(
                cdp.page.capture_screenshot(
                    format_="png", capture_beyond_viewport=req.full_page
                )
            )
        except Exception as cap_err:
            if not req.full_page:
                raise
            # Full-page capture fails on very tall/heavy pages (raster memory
            # pressure). A viewport shot is better than a 500.
            logger.warning(
                "full-page capture failed url=%s (%s: %s); retrying viewport-only",
                req.url, type(cap_err).__name__, cap_err,
            )
            img_b64 = driver.run_cdp_command(
                cdp.page.capture_screenshot(format_="png", capture_beyond_viewport=False)
            )
            degraded = True
        if not img_b64:
            raise RuntimeError("Chrome returned empty screenshot data")
        status, _ = get_response_meta(driver)
        body = {
            "screenshot": img_b64,
            "pageStatusCode": status,
            "title": driver.title or "",
        }
        if degraded:
            body["degraded"] = "full-page capture failed; captured viewport only"
        return body

    return run_on_driver(work)


def _scrape_sync(req: ScrapeRequest) -> dict:
    def work(driver: Driver) -> dict:
        apply_headers(driver, req.headers)
        navigate(driver, req.url, req.timeout, req.bypass_cloudflare)
        if req.wait_after_load > 0:
            time.sleep(req.wait_after_load / 1000)
        if req.check_selector:
            # Raises ElementWithSelectorNotFoundException on timeout, which
            # becomes the same 500 error shape camoufox produces.
            driver.wait_for_element(
                req.check_selector, wait=max(1, req.timeout // 1000)
            )
        content = driver.page_html
        status, content_type = get_response_meta(driver)
        body = {
            "content": content,
            "pageStatusCode": status,
            "contentType": content_type,
        }
        if status != 200:
            body["pageError"] = f"HTTP {status}"
        return body

    return run_on_driver(work)


async def run_with_budget(sync_fn, req, timeout_ms: int):
    # driver.get() self-terminates via its own timeout; this is a backstop
    # for a wedged Chrome. Generous so queued requests aren't killed while
    # waiting for a pool slot under load.
    budget = timeout_ms / 1000 + 90
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(executor, sync_fn, req), timeout=budget
    )


@app.get("/health")
async def health():
    return {"status": "ok", "browser": browser_ready, "headless": HEADLESS_MODE}


@app.post("/screenshot")
async def screenshot(req: ScreenshotRequest):
    t0 = time.monotonic()
    logger.info(
        "screenshot start url=%s full_page=%s timeout=%dms",
        req.url, req.full_page, req.timeout,
    )
    try:
        body = await run_with_budget(_screenshot_sync, req, req.timeout)
        logger.info(
            "screenshot ok url=%s bytes=%d elapsed=%.1fs%s",
            req.url, len(body["screenshot"]) * 3 // 4, time.monotonic() - t0,
            " (viewport fallback)" if "degraded" in body else "",
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


@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    t0 = time.monotonic()
    logger.info("scrape start url=%s timeout=%dms", req.url, req.timeout)
    try:
        body = await run_with_budget(_scrape_sync, req, req.timeout)
        logger.info(
            "scrape ok url=%s status=%d bytes=%d elapsed=%.1fs",
            req.url, body["pageStatusCode"], len(body["content"]), time.monotonic() - t0,
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
