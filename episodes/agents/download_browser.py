"""Playwright browser lifecycle for the download agent."""

import contextlib

from playwright.async_api import Page, async_playwright


@contextlib.asynccontextmanager
async def download_browser(download_dir: str) -> Page:
    """Yield a fresh Playwright page configured for the download agent.

    Headless-only, with downloads enabled, custom user-agent, and a 30-second
    default timeout.  Callers are responsible for saving downloads (e.g. into
    *download_dir*) via ``download.save_as(...)``.  Cleans up page -> context
    -> browser -> playwright in the ``finally`` block.
    """
    pw = await async_playwright().start()
    browser = None
    context = None
    page = None
    try:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            accept_downloads=True,
            user_agent="RAGtime/0.1 (podcast download agent)",
        )
        # Route downloads to the specified directory
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
