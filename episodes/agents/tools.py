"""Playwright browser tools for the recovery agent."""

import asyncio
import logging
import os

from playwright.async_api import Error as PlaywrightError
from pydantic_ai import RunContext

from .deps import RecoveryDeps

logger = logging.getLogger(__name__)

MAX_PAGE_TEXT = 15_000


async def navigate_to_url(ctx: RunContext[RecoveryDeps], url: str) -> str:
    """Navigate the browser to *url* and return the page title + text snippet."""
    page = ctx.deps.page
    try:
        await page.goto(url, wait_until="domcontentloaded")
        title = await page.title()
        text = await page.inner_text("body")
        snippet = text[:2000] if text else ""
        return f"Title: {title}\n\nContent preview:\n{snippet}"
    except PlaywrightError as exc:
        return f"Navigation failed: {exc}"


async def get_page_content(ctx: RunContext[RecoveryDeps]) -> str:
    """Return the current page's text content (truncated to 15k chars)."""
    page = ctx.deps.page
    try:
        text = await page.inner_text("body")
        return text[:MAX_PAGE_TEXT] if text else "(empty page)"
    except PlaywrightError as exc:
        return f"Failed to get page content: {exc}"


async def find_audio_links(ctx: RunContext[RecoveryDeps]) -> str:
    """Extract MP3 URLs from the current page.

    Looks in ``<audio>``, ``<source>``, ``<a>``, and ``<meta>`` tags for
    URLs containing ``.mp3`` extensions.
    """
    page = ctx.deps.page
    try:
        links = await page.evaluate("""() => {
            const urls = new Set();
            const audioExt = /\\.mp3(\\?|$)/i;

            // <audio src="..."> and <audio><source src="...">
            document.querySelectorAll('audio[src], audio source[src]').forEach(el => {
                const src = el.src || el.getAttribute('src');
                if (audioExt.test(src)) urls.add(src);
            });

            // <a href="..."> linking to audio files
            document.querySelectorAll('a[href]').forEach(el => {
                if (audioExt.test(el.href)) urls.add(el.href);
            });

            // <source> outside <audio> (some players)
            document.querySelectorAll('source[src]').forEach(el => {
                if (audioExt.test(el.src)) urls.add(el.src);
            });

            // <meta> tags with audio URLs (og:audio, etc.)
            document.querySelectorAll('meta[content]').forEach(el => {
                if (audioExt.test(el.content)) urls.add(el.content);
            });

            // data attributes that might contain audio URLs
            document.querySelectorAll('[data-src], [data-url], [data-audio]').forEach(el => {
                for (const attr of ['data-src', 'data-url', 'data-audio']) {
                    const val = el.getAttribute(attr);
                    if (val && audioExt.test(val)) urls.add(val);
                }
            });

            return [...urls].filter(Boolean);
        }""")
    except PlaywrightError as exc:
        return f"Failed to search for audio links: {exc}"
    if not links:
        return "No MP3 links found on the current page."
    return "MP3 links found:\n" + "\n".join(f"  - {url}" for url in links)


async def click_element(ctx: RunContext[RecoveryDeps], selector: str) -> str:
    """Click the element matching *selector* and return the resulting page state."""
    page = ctx.deps.page
    try:
        await page.click(selector)
        await page.wait_for_load_state("domcontentloaded")
        title = await page.title()
        url = page.url
        text = await page.inner_text("body")
        snippet = text[:2000] if text else ""
        return f"Clicked. Now at: {url}\nTitle: {title}\n\nContent preview:\n{snippet}"
    except PlaywrightError as exc:
        return f"Click failed for '{selector}': {exc}"


async def take_screenshot(ctx: RunContext[RecoveryDeps], label: str) -> str:
    """Take a screenshot and store it in deps.screenshots.

    Injects a small red CSS dot at the viewport center for visual debugging.
    Returns a confirmation message with the label.
    """
    page = ctx.deps.page
    try:
        # Inject a visible cursor dot via CSS
        await page.evaluate("""() => {
            if (!document.getElementById('ragtime-cursor')) {
                const dot = document.createElement('div');
                dot.id = 'ragtime-cursor';
                dot.style.cssText = 'position:fixed;width:12px;height:12px;' +
                    'background:red;border-radius:50%;pointer-events:none;z-index:99999;' +
                    'top:50%;left:50%;transform:translate(-50%,-50%);';
                document.body.appendChild(dot);
            }
        }""")
        png_bytes = await page.screenshot(full_page=False)
    except PlaywrightError as exc:
        return f"Screenshot failed: {exc}"

    ctx.deps.screenshots.append(png_bytes)

    # Attach image to the current Langfuse span so it's visible in the UI
    try:
        import langfuse
        from langfuse.media import LangfuseMedia

        media = LangfuseMedia(content_bytes=png_bytes, content_type="image/png")
        client = langfuse.get_client()
        client.update_current_span(output=media)
    except Exception:
        pass

    return f"Screenshot saved: {label} ({len(png_bytes)} bytes, #{len(ctx.deps.screenshots)})"


async def download_file(ctx: RunContext[RecoveryDeps], url: str) -> str:
    """Download a file from *url* and save it to the download directory.

    Saves as ``<episode_id>.mp3`` in ``deps.download_dir``.
    Returns the absolute path to the downloaded file.
    """
    page = ctx.deps.page
    filename = f"{ctx.deps.episode_id}.mp3"
    dest_path = os.path.join(ctx.deps.download_dir, filename)

    try:
        async with page.expect_download() as download_info:
            await page.goto(url)
        download = await download_info.value
        await download.save_as(dest_path)
        size = os.path.getsize(dest_path)
    except PlaywrightError as exc:
        return f"Download failed for '{url}': {exc}"
    except OSError as exc:
        return f"File error after download of '{url}': {exc}"

    return f"Downloaded to {dest_path} ({size} bytes)"


async def extract_text_by_selector(
    ctx: RunContext[RecoveryDeps], selector: str
) -> str:
    """Get the text content of all elements matching *selector*."""
    page = ctx.deps.page
    try:
        elements = await page.query_selector_all(selector)
    except PlaywrightError as exc:
        return f"Selector query failed for '{selector}': {exc}"
    texts = []
    for el in elements:
        try:
            text = await el.inner_text()
            if text and text.strip():
                texts.append(text.strip())
        except PlaywrightError:
            continue
    if not texts:
        return f"No elements found matching: {selector}"
    return "\n---\n".join(texts[:20])


async def translate_text(ctx: RunContext[RecoveryDeps], text: str) -> str:
    """Translate *text* to the episode's language using the LLM provider."""
    from ..languages import ISO_639_LANGUAGE_NAMES
    from ..providers.factory import get_translation_provider

    language = ctx.deps.language
    if not language:
        return "Cannot translate: episode language is unknown."

    language_name = ISO_639_LANGUAGE_NAMES.get(language)
    if not language_name:
        return f"Cannot translate: unsupported language code '{language}'."

    if language == "en":
        return text  # No translation needed

    try:
        provider = get_translation_provider()
        result = await asyncio.to_thread(
            provider.structured_extract,
            system_prompt=f"Translate the following text to {language_name}.",
            user_content=text,
            response_schema={
                "name": "translation",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "translated_text": {"type": "string"},
                    },
                    "required": ["translated_text"],
                    "additionalProperties": False,
                },
            },
        )
    except Exception as exc:
        logger.exception("Translation failed, returning original text: %s", exc)
        return text

    if not isinstance(result, dict):
        logger.warning(
            "Unexpected translation result type %s, returning original text.",
            type(result),
        )
        return text

    return result.get("translated_text", text)
