"""Tests for recovery agent Playwright tool functions."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from episodes.agents.deps import RecoveryDeps
    from episodes.agents.tools import (
        analyze_screenshot,
        click_at_coordinates,
        click_element,
        download_file,
        extract_text_by_selector,
        find_audio_links,
        get_page_content,
        intercept_audio_requests,
        navigate_to_url,
        take_screenshot,
        translate_text,
    )
except ImportError:
    raise unittest.SkipTest("pydantic-ai/playwright not installed")


def _make_deps(**overrides):
    """Build a RecoveryDeps with mock Playwright page."""
    page = AsyncMock()
    page.url = "https://example.com/episode/1"

    defaults = {
        "episode_id": 1,
        "episode_url": "https://example.com/episode/1",
        "audio_url": "",
        "language": "",
        "step_name": "scraping",
        "error_message": "403 Forbidden",
        "http_status": 403,
        "download_dir": "/tmp/test-downloads",
        "page": page,
        "screenshots": [],
    }
    defaults.update(overrides)
    return RecoveryDeps(**defaults)


def _make_ctx(deps=None):
    """Build a mock RunContext with the given deps."""
    ctx = MagicMock()
    ctx.deps = deps or _make_deps()
    return ctx


class NavigateToUrlTests(unittest.IsolatedAsyncioTestCase):
    async def test_navigates_and_returns_title_and_snippet(self):
        ctx = _make_ctx()
        ctx.deps.page.title.return_value = "Episode 42"
        ctx.deps.page.inner_text.return_value = "Welcome to the show" * 10

        result = await navigate_to_url(ctx, "https://example.com/ep/42")

        ctx.deps.page.goto.assert_awaited_once_with(
            "https://example.com/ep/42", wait_until="domcontentloaded"
        )
        self.assertIn("Episode 42", result)
        self.assertIn("Welcome to the show", result)

    async def test_handles_empty_body(self):
        ctx = _make_ctx()
        ctx.deps.page.title.return_value = "Empty Page"
        ctx.deps.page.inner_text.return_value = ""

        result = await navigate_to_url(ctx, "https://example.com/empty")
        self.assertIn("Empty Page", result)


class GetPageContentTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_truncated_content(self):
        ctx = _make_ctx()
        ctx.deps.page.inner_text.return_value = "x" * 20_000

        result = await get_page_content(ctx)
        self.assertEqual(len(result), 15_000)

    async def test_handles_empty_page(self):
        ctx = _make_ctx()
        ctx.deps.page.inner_text.return_value = ""

        result = await get_page_content(ctx)
        self.assertEqual(result, "(empty page)")


class FindAudioLinksTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_found_links(self):
        ctx = _make_ctx()
        ctx.deps.page.evaluate.return_value = [
            "https://cdn.example.com/ep42.mp3",
        ]

        result = await find_audio_links(ctx)
        self.assertIn("ep42.mp3", result)

    async def test_returns_message_when_no_links(self):
        ctx = _make_ctx()
        ctx.deps.page.evaluate.return_value = []

        result = await find_audio_links(ctx)
        self.assertIn("No MP3 links found", result)


class ClickElementTests(unittest.IsolatedAsyncioTestCase):
    async def test_clicks_and_returns_state(self):
        ctx = _make_ctx()
        ctx.deps.page.title.return_value = "Player Page"
        ctx.deps.page.url = "https://example.com/player"
        ctx.deps.page.inner_text.return_value = "Now playing"

        result = await click_element(ctx, "button.play")

        ctx.deps.page.click.assert_awaited_once_with("button.play")
        ctx.deps.page.wait_for_load_state.assert_awaited_once_with("domcontentloaded")
        self.assertIn("Player Page", result)
        self.assertIn("Now playing", result)


class TakeScreenshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_stores_screenshot_in_deps(self):
        ctx = _make_ctx()
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        ctx.deps.page.screenshot.return_value = png_data

        result = await take_screenshot(ctx, "debug-step-1")

        self.assertEqual(len(ctx.deps.screenshots), 1)
        self.assertEqual(ctx.deps.screenshots[0], png_data)
        self.assertIn("debug-step-1", result)
        self.assertIn("#1", result)

    async def test_appends_multiple_screenshots(self):
        ctx = _make_ctx()
        ctx.deps.page.screenshot.return_value = b"png1"

        await take_screenshot(ctx, "first")
        await take_screenshot(ctx, "second")

        self.assertEqual(len(ctx.deps.screenshots), 2)


class DownloadFileTests(unittest.IsolatedAsyncioTestCase):
    async def test_saves_file_to_download_dir(self):
        deps = _make_deps(download_dir="/tmp/test-dl")
        ctx = _make_ctx(deps)

        mock_download = AsyncMock()
        mock_download.save_as = AsyncMock()

        # Playwright's expect_download() returns a context manager.
        # __aenter__ yields an event object whose .value is awaitable and
        # resolves to the Download object.
        download_event = MagicMock()

        async def _get_download():
            return mock_download

        download_event.value = _get_download()

        download_cm = MagicMock()
        download_cm.__aenter__ = AsyncMock(return_value=download_event)
        download_cm.__aexit__ = AsyncMock(return_value=False)
        ctx.deps.page.expect_download = MagicMock(return_value=download_cm)

        with patch("episodes.agents.tools.os.path.getsize", return_value=1024):
            result = await download_file(ctx, "https://cdn.example.com/ep1.mp3")

        self.assertIn("/tmp/test-dl/1.mp3", result)
        self.assertIn("1024", result)


class ExtractTextBySelectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_matched_text(self):
        ctx = _make_ctx()
        el1 = AsyncMock()
        el1.inner_text.return_value = "Track 1"
        el2 = AsyncMock()
        el2.inner_text.return_value = "Track 2"
        ctx.deps.page.query_selector_all.return_value = [el1, el2]

        result = await extract_text_by_selector(ctx, "div.track")
        self.assertIn("Track 1", result)
        self.assertIn("Track 2", result)

    async def test_returns_message_when_no_match(self):
        ctx = _make_ctx()
        ctx.deps.page.query_selector_all.return_value = []

        result = await extract_text_by_selector(ctx, "div.nonexistent")
        self.assertIn("No elements found", result)


class TranslateTextTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_error_when_language_unknown(self):
        ctx = _make_ctx(_make_deps(language=""))
        result = await translate_text(ctx, "Download")
        self.assertIn("language is unknown", result)

    async def test_returns_error_for_invalid_language_code(self):
        ctx = _make_ctx(_make_deps(language="xyz"))
        result = await translate_text(ctx, "Download")
        self.assertIn("invalid language code", result)

    async def test_returns_text_unchanged_for_english(self):
        ctx = _make_ctx(_make_deps(language="en"))
        result = await translate_text(ctx, "Download")
        self.assertEqual(result, "Download")

    @patch("episodes.providers.factory.get_translation_provider")
    async def test_translates_via_llm_provider(self, mock_factory):
        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "translated_text": "Herunterladen"
        }
        mock_factory.return_value = mock_provider

        ctx = _make_ctx(_make_deps(language="de"))
        result = await translate_text(ctx, "Download")

        self.assertEqual(result, "Herunterladen")
        mock_provider.structured_extract.assert_called_once()
        call_kwargs = mock_provider.structured_extract.call_args
        self.assertIn("German", call_kwargs.kwargs.get("system_prompt", call_kwargs.args[0] if call_kwargs.args else ""))

    @patch("episodes.providers.factory.get_translation_provider")
    async def test_returns_original_text_on_provider_error(self, mock_factory):
        mock_factory.side_effect = ValueError("RAGTIME_TRANSLATION_API_KEY is not set")

        ctx = _make_ctx(_make_deps(language="de"))
        result = await translate_text(ctx, "Download")

        self.assertEqual(result, "Download")

    @patch("episodes.providers.factory.get_translation_provider")
    async def test_returns_original_text_on_llm_error(self, mock_factory):
        mock_provider = MagicMock()
        mock_provider.structured_extract.side_effect = Exception("API rate limit")
        mock_factory.return_value = mock_provider

        ctx = _make_ctx(_make_deps(language="de"))
        result = await translate_text(ctx, "Download")

        self.assertEqual(result, "Download")


class AnalyzeScreenshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_tool_return_with_image(self):
        ctx = _make_ctx()
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        ctx.deps.page.screenshot.return_value = png_data

        from pydantic_ai.messages import ToolReturn

        result = await analyze_screenshot(ctx, "visual-check")

        self.assertIsInstance(result, ToolReturn)
        self.assertIn("visual-check", result.return_value)
        self.assertEqual(len(ctx.deps.screenshots), 1)
        # content should contain the image
        self.assertEqual(len(result.content), 2)

    async def test_handles_screenshot_failure(self):
        from playwright.async_api import Error as PwError
        from pydantic_ai.messages import ToolReturn

        ctx = _make_ctx()
        ctx.deps.page.screenshot.side_effect = PwError("Browser crashed")

        result = await analyze_screenshot(ctx, "fail-test")

        self.assertIsInstance(result, ToolReturn)
        self.assertIn("Screenshot failed", result.return_value)


class ClickAtCoordinatesTests(unittest.IsolatedAsyncioTestCase):
    async def test_clicks_and_returns_state(self):
        ctx = _make_ctx()
        ctx.deps.page.title.return_value = "After Click"
        ctx.deps.page.url = "https://example.com/page"
        ctx.deps.page.inner_text.return_value = "New content"

        result = await click_at_coordinates(ctx, 350, 420)

        ctx.deps.page.mouse.click.assert_awaited_once_with(350, 420)
        self.assertIn("350", result)
        self.assertIn("420", result)
        self.assertIn("After Click", result)


class InterceptAudioRequestsTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_message_when_no_audio(self):
        ctx = _make_ctx()
        handlers = {}

        def mock_on(event, handler):
            handlers[event] = handler

        ctx.deps.page.on = mock_on
        ctx.deps.page.remove_listener = MagicMock()

        result = await intercept_audio_requests(ctx, "button.play")

        ctx.deps.page.click.assert_awaited_once_with("button.play")
        self.assertIn("No audio requests intercepted", result)

    async def test_handles_coordinate_action(self):
        ctx = _make_ctx()
        ctx.deps.page.on = MagicMock()
        ctx.deps.page.remove_listener = MagicMock()

        result = await intercept_audio_requests(ctx, "coordinates:100,200")

        ctx.deps.page.mouse.click.assert_awaited_once_with(100, 200)
