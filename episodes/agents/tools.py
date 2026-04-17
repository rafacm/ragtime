"""Playwright browser tools for the recovery agent."""

import asyncio
import logging
import os

from playwright.async_api import Error as PlaywrightError
from pydantic_ai import RunContext
from pydantic_ai.messages import BinaryImage, ToolReturn

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
    """Click the element matching *selector* and return the resulting page state.

    Use Playwright selector syntax. To match by text content use:
      button:has-text("Download")    — button containing "Download"
      a:has-text("Information")      — link containing "Information"
      text="Exact text"              — exact text match
    Do NOT use CSS :contains() — it is not supported.
    """
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
    from .. import telemetry

    if telemetry.is_langfuse_enabled():
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

    Uses the browser's API request context, which shares cookies and
    session state with the page. This handles both direct downloads and
    streaming audio that wouldn't trigger a browser download event.

    Saves as ``<episode_id>.mp3`` in ``deps.download_dir``.
    Returns the absolute path to the downloaded file.
    """
    page = ctx.deps.page
    filename = f"{ctx.deps.episode_id}.mp3"
    dest_path = os.path.join(ctx.deps.download_dir, filename)

    try:
        response = await page.context.request.get(url)
        if not response.ok:
            return f"Download failed for '{url}': HTTP {response.status}"
        raw_content_type = response.headers.get("content-type")
        content_type = ""
        if raw_content_type:
            content_type = raw_content_type.split(";", 1)[0].strip().lower()
        allowed_mp3_types = {"audio/mpeg", "audio/mp3"}
        if content_type:
            if content_type not in allowed_mp3_types:
                if content_type.startswith("audio/"):
                    return (
                        f"Download rejected for '{url}': unsupported audio "
                        f"Content-Type '{raw_content_type}'. Only MP3 audio "
                        "('audio/mpeg' or 'audio/mp3') is supported."
                    )
                return (
                    f"Download rejected for '{url}': expected MP3 audio content "
                    f"but got '{raw_content_type}'. This may be a login page or error page."
                )
        else:
            url_path = url.split("?", 1)[0].lower()
            if not url_path.endswith(".mp3"):
                return (
                    f"Download rejected for '{url}': missing Content-Type header "
                    "and URL does not look like an MP3 file. Only MP3 downloads are supported."
                )
        body = await response.body()
        with open(dest_path, "wb") as f:
            f.write(body)
        size = len(body)
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
    from ..languages import ISO_639_LANGUAGE_NAMES, ISO_639_RE
    from ..providers.factory import get_translation_provider

    language = ctx.deps.language
    if not language:
        return "Cannot translate: episode language is unknown."

    if not ISO_639_RE.match(language):
        return f"Cannot translate: invalid language code '{language}'."

    language_name = ISO_639_LANGUAGE_NAMES.get(language, language)

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


async def analyze_screenshot(ctx: RunContext[RecoveryDeps], label: str) -> ToolReturn:
    """Take a screenshot and return it for visual analysis.

    Use this to visually inspect the page — for example, to find three-dot
    menus (⋮ or ⋯), play buttons, or other interactive elements that are
    not easily found via CSS selectors. Describe what you see and use
    click_at_coordinates to interact with elements you identify visually.
    """
    page = ctx.deps.page
    try:
        png_bytes = await page.screenshot(full_page=False)
    except PlaywrightError as exc:
        return ToolReturn(return_value=f"Screenshot failed: {exc}")

    ctx.deps.screenshots.append(png_bytes)

    # Attach to Langfuse when active
    from .. import telemetry

    if telemetry.is_langfuse_enabled():
        try:
            import langfuse
            from langfuse.media import LangfuseMedia

            media = LangfuseMedia(content_bytes=png_bytes, content_type="image/png")
            client = langfuse.get_client()
            client.update_current_span(output=media)
        except Exception:
            pass

    image = BinaryImage(data=png_bytes, media_type="image/png")
    return ToolReturn(
        return_value=f"Screenshot taken: {label} ({len(png_bytes)} bytes). Analyze the image to find interactive elements.",
        content=[f"Screenshot '{label}':", image],
    )


async def click_at_coordinates(
    ctx: RunContext[RecoveryDeps], x: int, y: int
) -> str:
    """Click at pixel coordinates (x, y) on the page.

    Use this after visually identifying an element via analyze_screenshot.
    Coordinates are relative to the viewport (0,0 is top-left).
    """
    page = ctx.deps.page
    try:
        await page.mouse.click(x, y)
        await page.wait_for_load_state("domcontentloaded")
        title = await page.title()
        url = page.url
        text = await page.inner_text("body")
        snippet = text[:2000] if text else ""
        return f"Clicked at ({x}, {y}). Now at: {url}\nTitle: {title}\n\nContent preview:\n{snippet}"
    except PlaywrightError as exc:
        return f"Click at ({x}, {y}) failed: {exc}"


async def intercept_audio_requests(
    ctx: RunContext[RecoveryDeps], action_selector: str
) -> str:
    """Click *action_selector* while intercepting network requests for audio.

    Listens for requests with audio MIME types (mp3, mpeg, ogg, wav, aac,
    m4a) or audio file extensions. Use this to capture the audio URL when
    clicking a play button triggers streaming rather than a direct download.

    Use Playwright selector syntax for *action_selector* (e.g.
    ``button:has-text("Play")``), or pass pixel coordinates as
    ``coordinates:X,Y`` (e.g. ``coordinates:350,420``).
    """
    page = ctx.deps.page
    audio_urls: list[str] = []
    audio_found = asyncio.Event()

    audio_extensions = (".mp3", ".ogg", ".wav", ".aac", ".m4a", ".opus")
    audio_mimes = ("audio/", "application/ogg")

    def _record(url: str):
        audio_urls.append(url)
        audio_found.set()

    def on_request(request):
        url = request.url
        path = url.split("?")[0].lower()
        if any(path.endswith(ext) for ext in audio_extensions):
            _record(url)

    def on_response(response):
        content_type = response.headers.get("content-type", "")
        if any(mime in content_type for mime in audio_mimes):
            _record(response.url)

    page.on("request", on_request)
    page.on("response", on_response)

    try:
        # Perform the click action
        if action_selector.startswith("coordinates:"):
            coords = action_selector.removeprefix("coordinates:").split(",")
            x, y = int(coords[0].strip()), int(coords[1].strip())
            await page.mouse.click(x, y)
        else:
            await page.click(action_selector)

        # Wait for audio request or timeout after 5 seconds
        try:
            await asyncio.wait_for(audio_found.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass

    except PlaywrightError as exc:
        return f"Action failed for '{action_selector}': {exc}"
    finally:
        page.remove_listener("request", on_request)
        page.remove_listener("response", on_response)

    if not audio_urls:
        return "No audio requests intercepted. The click may not have triggered audio playback."

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for url in audio_urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)

    return "Intercepted audio URLs:\n" + "\n".join(f"  - {url}" for url in unique)
