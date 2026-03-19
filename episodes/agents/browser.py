"""Playwright browser lifecycle for recovery attempts."""

import contextlib

from playwright.async_api import Page, async_playwright


@contextlib.asynccontextmanager
async def recovery_browser(download_dir: str) -> Page:
    """Yield a fresh Playwright page configured for recovery.

    Headless-only, accepts downloads into *download_dir*, custom user-agent,
    and a 30-second default timeout.  Cleans up page → context → browser →
    playwright in the ``finally`` block.
    """
    pw = await async_playwright().start()
    browser = None
    context = None
    page = None
    try:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            accept_downloads=True,
            user_agent="RAGtime/0.1 (podcast recovery agent)",
        )
        page = await context.new_page()
        page.set_default_timeout(30_000)
        yield page
    finally:
        if page:
            await page.close()
        if context:
            await context.close()
        if browser:
            await browser.close()
        await pw.stop()
