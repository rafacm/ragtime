from datetime import date
from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.test import TestCase, override_settings

from .models import Episode
from .scraper import clean_html, scrape_episode


@patch("episodes.signals.async_task")
class EpisodeModelTests(TestCase):
    def test_default_status_is_pending(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/episode/1")
        self.assertEqual(episode.status, Episode.Status.PENDING)

    def test_url_uniqueness(self, mock_async):
        Episode.objects.create(url="https://example.com/episode/1")
        with self.assertRaises(IntegrityError):
            Episode.objects.create(url="https://example.com/episode/1")

    def test_str_returns_title_when_set(self, mock_async):
        episode = Episode(url="https://example.com/ep/1", title="My Episode")
        self.assertEqual(str(episode), "My Episode")

    def test_str_returns_url_when_no_title(self, mock_async):
        episode = Episode(url="https://example.com/ep/1")
        self.assertEqual(str(episode), "https://example.com/ep/1")

    def test_new_statuses_exist(self, mock_async):
        self.assertEqual(Episode.Status.SCRAPING, "scraping")
        self.assertEqual(Episode.Status.NEEDS_REVIEW, "needs_review")

    def test_metadata_fields_blank_by_default(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/1")
        self.assertEqual(episode.title, "")
        self.assertEqual(episode.description, "")
        self.assertIsNone(episode.published_at)
        self.assertEqual(episode.image_url, "")
        self.assertEqual(episode.language, "")
        self.assertEqual(episode.audio_url, "")
        self.assertEqual(episode.scraped_html, "")


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
    RAGTIME_LLM_PROVIDER="openai",
    RAGTIME_LLM_API_KEY="test-key",
    RAGTIME_LLM_MODEL="gpt-4.1-mini",
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

    @patch("episodes.scraper.get_llm_provider")
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

    @patch("episodes.scraper.get_llm_provider")
    @patch("episodes.scraper.fetch_html")
    def test_incomplete_extraction_needs_review(self, mock_fetch, mock_provider_factory):
        mock_fetch.return_value = self.SAMPLE_HTML
        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = self.LLM_INCOMPLETE_RESPONSE
        mock_provider_factory.return_value = mock_provider

        episode = self._create_episode(url="https://example.com/ep/2")
        scrape_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.NEEDS_REVIEW)
        self.assertEqual(episode.title, "Jazz Episode 1")
        self.assertEqual(episode.audio_url, "")  # Was null in response

    @patch("episodes.scraper.fetch_html")
    def test_http_error_sets_failed(self, mock_fetch):
        mock_fetch.side_effect = Exception("Connection refused")

        episode = self._create_episode(url="https://example.com/ep/3")
        scrape_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)

    @patch("episodes.scraper.get_llm_provider")
    def test_reprocess_with_user_filled_fields(self, mock_provider_factory):
        """When user fills required fields and reprocesses, LLM is skipped."""
        episode = self._create_episode(
            url="https://example.com/ep/4",
            title="Filled by user",
            audio_url="https://example.com/audio.mp3",
            scraped_html="<html>cached</html>",
            status=Episode.Status.NEEDS_REVIEW,
        )

        scrape_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.DOWNLOADING)
        # LLM should not have been called
        mock_provider_factory.assert_not_called()

    @patch("episodes.scraper.get_llm_provider")
    @patch("episodes.scraper.fetch_html")
    def test_uses_cached_html_on_reprocess(self, mock_fetch, mock_provider_factory):
        """When scraped_html is already stored, HTTP fetch is skipped."""
        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = self.LLM_COMPLETE_RESPONSE
        mock_provider_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/5",
            scraped_html="<html>cached</html>",
            status=Episode.Status.NEEDS_REVIEW,
        )

        scrape_episode(episode.pk)

        mock_fetch.assert_not_called()
        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.DOWNLOADING)

    def test_nonexistent_episode(self):
        # Should not raise, just log error
        scrape_episode(99999)


class SignalTests(TestCase):
    @patch("episodes.signals.async_task")
    def test_creating_episode_queues_scrape(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/signal-1")
        mock_async.assert_called_once_with(
            "episodes.scraper.scrape_episode", episode.pk
        )

    @patch("episodes.signals.async_task")
    def test_updating_episode_does_not_requeue(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/signal-2")
        mock_async.reset_mock()

        episode.title = "Updated"
        episode.save()

        mock_async.assert_not_called()


class EpisodeAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import User

        cls.admin_user = User.objects.create_superuser(
            username="admin", password="testpass"
        )

    def setUp(self):
        self.client.login(username="admin", password="testpass")

    def test_changelist_loads(self):
        response = self.client.get("/admin/episodes/episode/")
        self.assertEqual(response.status_code, 200)

    def test_add_form_loads(self):
        response = self.client.get("/admin/episodes/episode/add/")
        self.assertEqual(response.status_code, 200)

    @patch("episodes.signals.async_task")
    def test_detail_page_loads(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/admin-1")
        response = self.client.get(f"/admin/episodes/episode/{episode.pk}/change/")
        self.assertEqual(response.status_code, 200)

    @patch("episodes.signals.async_task")
    def test_reprocess_action(self, mock_async):
        episode = Episode.objects.create(
            url="https://example.com/ep/admin-2",
            status=Episode.Status.NEEDS_REVIEW,
        )
        mock_async.reset_mock()

        with patch("episodes.admin.async_task") as mock_admin_async:
            response = self.client.post(
                "/admin/episodes/episode/",
                {
                    "action": "reprocess",
                    "_selected_action": [episode.pk],
                },
                follow=True,
            )
            self.assertEqual(response.status_code, 200)
            mock_admin_async.assert_called_once_with(
                "episodes.scraper.scrape_episode", episode.pk
            )

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.SCRAPING)

    @patch("episodes.signals.async_task")
    def test_metadata_fields_editable_in_needs_review(self, mock_async):
        episode = Episode.objects.create(
            url="https://example.com/ep/admin-3",
            status=Episode.Status.NEEDS_REVIEW,
        )
        response = self.client.get(f"/admin/episodes/episode/{episode.pk}/change/")
        content = response.content.decode()
        # title field should be an input (editable), not in readonly
        self.assertIn('name="title"', content)
