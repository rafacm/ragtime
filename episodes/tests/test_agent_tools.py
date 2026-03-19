"""Tests for recovery agent Playwright tool functions."""

from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase

from episodes.agents.deps import RecoveryDeps
from episodes.agents.tools import (
    click_element,
    download_file,
    extract_text_by_selector,
    find_audio_links,
    get_page_content,
    navigate_to_url,
    take_screenshot,
)


def _make_deps(**overrides):
    """Build a RecoveryDeps with mock Playwright page."""
    page = AsyncMock()
    page.url = "https://example.com/episode/1"

    defaults = {
        "episode_id": 1,
        "episode_url": "https://example.com/episode/1",
        "audio_url": "",
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


class NavigateToUrlTests(TestCase):
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


class GetPageContentTests(TestCase):
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


class FindAudioLinksTests(TestCase):
    async def test_returns_found_links(self):
        ctx = _make_ctx()
        ctx.deps.page.evaluate.return_value = [
            "https://cdn.example.com/ep42.mp3",
            "https://cdn.example.com/ep42.ogg",
        ]

        result = await find_audio_links(ctx)
        self.assertIn("ep42.mp3", result)
        self.assertIn("ep42.ogg", result)

    async def test_returns_message_when_no_links(self):
        ctx = _make_ctx()
        ctx.deps.page.evaluate.return_value = []

        result = await find_audio_links(ctx)
        self.assertIn("No audio links found", result)


class ClickElementTests(TestCase):
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


class TakeScreenshotTests(TestCase):
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


class DownloadFileTests(TestCase):
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


class ExtractTextBySelectorTests(TestCase):
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
