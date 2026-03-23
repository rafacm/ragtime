from datetime import date
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from episodes.models import Episode
from episodes.scraper import clean_html, scrape_episode


class CleanHtmlTests(TestCase):
    def test_strips_script_tags(self):
        html = "<html><body><script>alert('x')</script><p>Hello</p></body></html>"
        result = clean_html(html)
        self.assertNotIn("script", result)
        self.assertIn("Hello", result)

    def test_strips_style_tags(self):
        html = "<html><body><style>body{color:red}</style><p>Hello</p></body></html>"
        result = clean_html(html)
        self.assertNotIn("style", result)
        self.assertIn("Hello", result)

    def test_strips_nav_and_footer(self):
        html = "<html><body><nav>Menu</nav><p>Content</p><footer>Foot</footer></body></html>"
        result = clean_html(html)
        self.assertNotIn("Menu", result)
        self.assertNotIn("Foot", result)
        self.assertIn("Content", result)

    def test_preserves_meta_tags(self):
        html = '<html><head><meta property="og:title" content="Ep 1"></head><body></body></html>'
        result = clean_html(html)
        self.assertIn("og:title", result)

    def test_preserves_audio_tags(self):
        html = '<html><body><audio><source src="episode.mp3"></audio></body></html>'
        result = clean_html(html)
        self.assertIn("episode.mp3", result)

    def test_truncates_long_html(self):
        html = "<p>" + "x" * 40_000 + "</p>"
        result = clean_html(html)
        self.assertLessEqual(len(result), 30_000)


@override_settings(
    RAGTIME_SCRAPING_PROVIDER="openai",
    RAGTIME_SCRAPING_API_KEY="test-key",
    RAGTIME_SCRAPING_MODEL="gpt-4.1-mini",
)
class ScrapeEpisodeTests(TestCase):
    """Tests for the scrape_episode task function with mocked HTTP and LLM."""

    SAMPLE_HTML = """
    <html>
    <head>
        <meta property="og:title" content="Jazz Episode 1">
    </head>
    <body>
        <h1>Jazz Episode 1</h1>
        <p>A great episode about jazz.</p>
        <audio><source src="https://example.com/ep1.mp3"></audio>
    </body>
    </html>
    """

    LLM_COMPLETE_RESPONSE = {
        "title": "Jazz Episode 1",
        "description": "A great episode about jazz.",
        "published_at": "2026-01-15",
        "image_url": "https://example.com/image.jpg",
        "language": "en",
        "audio_url": "https://example.com/ep1.mp3",
    }

    LLM_INCOMPLETE_RESPONSE = {
        "title": "Jazz Episode 1",
        "description": "A great episode about jazz.",
        "published_at": None,
        "image_url": None,
        "language": "en",
        "audio_url": None,  # Missing required field
    }

    def _create_episode(self, **kwargs):
        """Create episode without triggering post_save signal."""
        with patch("episodes.signals.async_task"):
            return Episode.objects.create(**kwargs)

    @patch("episodes.scraper.get_scraping_provider")
    @patch("episodes.scraper.fetch_html")
    def test_success_path(self, mock_fetch, mock_provider_factory):
        mock_fetch.return_value = self.SAMPLE_HTML
        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = self.LLM_COMPLETE_RESPONSE
        mock_provider_factory.return_value = mock_provider

        episode = self._create_episode(url="https://example.com/ep/1")
        scrape_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.DOWNLOADING)
        self.assertEqual(episode.title, "Jazz Episode 1")
        self.assertEqual(episode.audio_url, "https://example.com/ep1.mp3")
        self.assertEqual(episode.language, "en")
        self.assertEqual(episode.published_at, date(2026, 1, 15))
        self.assertNotEqual(episode.scraped_html, "")

    @patch("episodes.scraper.get_scraping_provider")
    @patch("episodes.scraper.fetch_html")
    def test_incomplete_extraction_fails(self, mock_fetch, mock_provider_factory):
        mock_fetch.return_value = self.SAMPLE_HTML
        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = self.LLM_INCOMPLETE_RESPONSE
        mock_provider_factory.return_value = mock_provider

        episode = self._create_episode(url="https://example.com/ep/2")
        scrape_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertEqual(episode.title, "Jazz Episode 1")
        self.assertEqual(episode.audio_url, "")  # Was null in response
        self.assertIn("Incomplete metadata", episode.error_message)

    @patch("episodes.scraper.fetch_html")
    def test_http_error_sets_failed(self, mock_fetch):
        mock_fetch.side_effect = Exception("Connection refused")

        episode = self._create_episode(url="https://example.com/ep/3")
        scrape_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)

    @patch("episodes.scraper.get_scraping_provider")
    def test_reprocess_with_user_filled_fields(self, mock_provider_factory):
        """When user fills required fields and reprocesses, LLM is skipped."""
        episode = self._create_episode(
            url="https://example.com/ep/4",
            title="Filled by user",
            audio_url="https://example.com/audio.mp3",
            scraped_html="<html>cached</html>",
            status=Episode.Status.FAILED,
        )

        scrape_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.DOWNLOADING)
        # LLM should not have been called
        mock_provider_factory.assert_not_called()

    @patch("episodes.scraper.get_scraping_provider")
    @patch("episodes.scraper.fetch_html")
    def test_uses_cached_html_on_reprocess(self, mock_fetch, mock_provider_factory):
        """When scraped_html is already stored, HTTP fetch is skipped."""
        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = self.LLM_COMPLETE_RESPONSE
        mock_provider_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/5",
            scraped_html="<html>cached</html>",
            status=Episode.Status.FAILED,
        )

        scrape_episode(episode.pk)

        mock_fetch.assert_not_called()
        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.DOWNLOADING)

    @patch("episodes.signals.async_task")
    @patch("episodes.scraper.get_scraping_provider")
    @patch("episodes.scraper.fetch_html")
    def test_success_queues_download_task(self, mock_fetch, mock_provider_factory, mock_async):
        """LLM extraction path triggers download task via signal."""
        mock_fetch.return_value = self.SAMPLE_HTML
        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = self.LLM_COMPLETE_RESPONSE
        mock_provider_factory.return_value = mock_provider

        episode = Episode.objects.create(url="https://example.com/ep/6")
        mock_async.reset_mock()

        scrape_episode(episode.pk)

        mock_async.assert_called_with(
            "episodes.downloader.download_episode", episode.pk
        )

    @patch("episodes.scraper.get_scraping_provider")
    @patch("episodes.scraper.fetch_html")
    def test_incomplete_metadata_does_not_overwrite_recovery_status(
        self, mock_fetch, mock_provider_factory
    ):
        """When recovery changes the status during fail_step, the scraper must not overwrite it.

        Regression test: the scraper used to call fail_step() before episode.save(),
        so synchronous recovery could set status=TRANSCRIBING, only for the scraper's
        subsequent save() to overwrite it back to FAILED.
        """
        mock_fetch.return_value = self.SAMPLE_HTML
        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = self.LLM_INCOMPLETE_RESPONSE
        mock_provider_factory.return_value = mock_provider

        episode = self._create_episode(url="https://example.com/ep/recovery")

        def fake_recovery(sender, event, pipeline_event, **kwargs):
            """Simulate agent recovery setting TRANSCRIBING during fail_step signal."""
            ep = Episode.objects.get(pk=event.episode_id)
            ep.status = Episode.Status.TRANSCRIBING
            ep.error_message = ""
            ep.save(update_fields=["status", "error_message", "updated_at"])

        from episodes.signals import step_failed

        step_failed.connect(fake_recovery)
        try:
            scrape_episode(episode.pk)
        finally:
            step_failed.disconnect(fake_recovery)

        episode.refresh_from_db()
        self.assertEqual(
            episode.status,
            Episode.Status.TRANSCRIBING,
            "Scraper save() must not overwrite recovery status back to FAILED",
        )

    def test_nonexistent_episode(self):
        # Should not raise, just log error
        scrape_episode(99999)
