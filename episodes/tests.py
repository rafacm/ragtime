import os
import tempfile
from datetime import date
from unittest.mock import MagicMock, PropertyMock, call, patch

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


# ---------------------------------------------------------------------------
# Step 4: Download tests
# ---------------------------------------------------------------------------


@override_settings(RAGTIME_MAX_AUDIO_SIZE=25 * 1024 * 1024)
class DownloadEpisodeTests(TestCase):
    """Tests for the download_episode task function."""

    def _create_episode(self, **kwargs):
        with patch("episodes.signals.async_task"):
            return Episode.objects.create(**kwargs)

    @patch("episodes.downloader.httpx.stream")
    def test_success_small_file(self, mock_stream):
        """Download ≤ 25MB → status transcribing."""
        from episodes.downloader import download_episode

        # Mock streaming response with small content
        audio_data = b"fake-mp3-data" * 100  # small file
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.iter_bytes.return_value = [audio_data]
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_stream.return_value = mock_response

        episode = self._create_episode(
            url="https://example.com/ep/dl-1",
            audio_url="https://example.com/ep1.mp3",
            status=Episode.Status.DOWNLOADING,
        )

        with patch("episodes.signals.async_task"):
            download_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.TRANSCRIBING)
        self.assertTrue(episode.audio_file)

    @patch("episodes.downloader.httpx.stream")
    @override_settings(RAGTIME_MAX_AUDIO_SIZE=100)  # 100 bytes limit
    def test_large_file_triggers_resize(self, mock_stream):
        """Download > max size → status resizing."""
        from episodes.downloader import download_episode

        audio_data = b"x" * 200  # exceeds 100 byte limit
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.iter_bytes.return_value = [audio_data]
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_stream.return_value = mock_response

        episode = self._create_episode(
            url="https://example.com/ep/dl-2",
            audio_url="https://example.com/ep2.mp3",
            status=Episode.Status.DOWNLOADING,
        )

        with patch("episodes.signals.async_task"):
            download_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.RESIZING)

    @patch("episodes.downloader.httpx.stream")
    def test_http_error_sets_failed(self, mock_stream):
        """HTTP error → status failed with error_message."""
        from episodes.downloader import download_episode

        mock_stream.side_effect = Exception("Connection refused")

        episode = self._create_episode(
            url="https://example.com/ep/dl-3",
            audio_url="https://example.com/ep3.mp3",
            status=Episode.Status.DOWNLOADING,
        )

        with patch("episodes.signals.async_task"):
            download_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("Connection refused", episode.error_message)

    def test_nonexistent_episode(self):
        """Non-existent episode ID → no crash."""
        from episodes.downloader import download_episode

        download_episode(99999)  # should not raise

    def test_wrong_status_skips(self):
        """Episode not in 'downloading' status → skip."""
        from episodes.downloader import download_episode

        episode = self._create_episode(
            url="https://example.com/ep/dl-4",
            status=Episode.Status.PENDING,
        )

        download_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.PENDING)


# ---------------------------------------------------------------------------
# Step 5: Resize tests
# ---------------------------------------------------------------------------


class ResizeEpisodeTests(TestCase):
    """Tests for the resize_episode task function."""

    def _create_episode_with_audio(self, **kwargs):
        """Create an episode with a real temporary audio file."""
        from django.core.files.base import ContentFile

        with patch("episodes.signals.async_task"):
            episode = Episode.objects.create(**kwargs)
            # Save a fake audio file
            episode.audio_file.save(
                f"{episode.pk}.mp3",
                ContentFile(b"fake-audio-data" * 100),
                save=True,
            )
        return episode

    def _create_episode(self, **kwargs):
        with patch("episodes.signals.async_task"):
            return Episode.objects.create(**kwargs)

    @patch("episodes.resizer.subprocess.run")
    @patch("episodes.resizer.shutil.which", return_value="/usr/bin/ffmpeg")
    @override_settings(RAGTIME_MAX_AUDIO_SIZE=25 * 1024 * 1024)
    def test_success_resize(self, mock_which, mock_run):
        """Successful resize → status transcribing."""
        from episodes.resizer import resize_episode

        episode = self._create_episode_with_audio(
            url="https://example.com/ep/rs-1",
            status=Episode.Status.RESIZING,
        )

        # Mock ffmpeg success — write a small file to the output path
        def fake_ffmpeg(args, **kw):
            output_path = args[-1]  # last arg is output file
            with open(output_path, "wb") as f:
                f.write(b"resized-audio" * 10)  # small output
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        with patch("episodes.signals.async_task"):
            resize_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.TRANSCRIBING)

    @patch("episodes.resizer.subprocess.run")
    @patch("episodes.resizer.shutil.which", return_value="/usr/bin/ffmpeg")
    @override_settings(RAGTIME_MAX_AUDIO_SIZE=50)  # 50 bytes limit
    def test_still_too_large_after_resize(self, mock_which, mock_run):
        """Resized file still > max → status failed."""
        from episodes.resizer import resize_episode

        episode = self._create_episode_with_audio(
            url="https://example.com/ep/rs-2",
            status=Episode.Status.RESIZING,
        )

        def fake_ffmpeg(args, **kw):
            output_path = args[-1]
            with open(output_path, "wb") as f:
                f.write(b"x" * 200)  # still too large
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        with patch("episodes.signals.async_task"):
            resize_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("exceeds 25MB after resizing", episode.error_message)

    @patch("episodes.resizer.subprocess.run")
    @patch("episodes.resizer.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_ffmpeg_error(self, mock_which, mock_run):
        """ffmpeg returns non-zero → status failed."""
        from episodes.resizer import resize_episode

        episode = self._create_episode_with_audio(
            url="https://example.com/ep/rs-3",
            status=Episode.Status.RESIZING,
        )

        mock_run.return_value = MagicMock(
            returncode=1, stderr=b"Invalid input file"
        )

        with patch("episodes.signals.async_task"):
            resize_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("ffmpeg failed", episode.error_message)

    @patch("episodes.resizer.shutil.which", return_value=None)
    def test_ffmpeg_not_installed(self, mock_which):
        """ffmpeg not on PATH → status failed with helpful message."""
        from episodes.resizer import resize_episode

        episode = self._create_episode_with_audio(
            url="https://example.com/ep/rs-4",
            status=Episode.Status.RESIZING,
        )

        with patch("episodes.signals.async_task"):
            resize_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("ffmpeg is not installed", episode.error_message)

    def test_no_audio_file(self):
        """No audio file → status failed."""
        from episodes.resizer import resize_episode

        episode = self._create_episode(
            url="https://example.com/ep/rs-5",
            status=Episode.Status.RESIZING,
        )

        with patch("episodes.signals.async_task"):
            resize_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("No audio file", episode.error_message)

    def test_nonexistent_episode(self):
        from episodes.resizer import resize_episode

        resize_episode(99999)  # should not raise


# ---------------------------------------------------------------------------
# Updated signal tests for download/resize triggers
# ---------------------------------------------------------------------------


class DownloadResizeSignalTests(TestCase):
    @patch("episodes.signals.async_task")
    def test_status_change_to_downloading_queues_download(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/sig-dl-1")
        mock_async.reset_mock()

        episode.status = Episode.Status.DOWNLOADING
        episode.save(update_fields=["status", "updated_at"])

        mock_async.assert_called_once_with(
            "episodes.downloader.download_episode", episode.pk
        )

    @patch("episodes.signals.async_task")
    def test_status_change_to_resizing_queues_resize(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/sig-rs-1")
        mock_async.reset_mock()

        episode.status = Episode.Status.RESIZING
        episode.save(update_fields=["status", "updated_at"])

        mock_async.assert_called_once_with(
            "episodes.resizer.resize_episode", episode.pk
        )

    @patch("episodes.signals.async_task")
    def test_other_status_change_does_not_queue(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/sig-other")
        mock_async.reset_mock()

        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "updated_at"])

        mock_async.assert_not_called()

    @patch("episodes.signals.async_task")
    def test_save_without_update_fields_does_not_queue(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/sig-nuf")
        mock_async.reset_mock()

        episode.status = Episode.Status.DOWNLOADING
        episode.save()  # no update_fields

        mock_async.assert_not_called()


# ---------------------------------------------------------------------------
# Step 6: Transcribe tests
# ---------------------------------------------------------------------------

SAMPLE_WHISPER_RESPONSE = {
    "task": "transcribe",
    "language": "english",
    "duration": 120.0,
    "text": "Hello, welcome to the jazz podcast.",
    "segments": [
        {
            "id": 0,
            "start": 0.0,
            "end": 3.5,
            "text": "Hello, welcome to the jazz podcast.",
        }
    ],
    "words": [
        {"word": "Hello,", "start": 0.0, "end": 0.5},
        {"word": "welcome", "start": 0.6, "end": 1.0},
        {"word": "to", "start": 1.0, "end": 1.1},
        {"word": "the", "start": 1.1, "end": 1.2},
        {"word": "jazz", "start": 1.2, "end": 1.5},
        {"word": "podcast.", "start": 1.5, "end": 2.0},
    ],
}


@override_settings(
    RAGTIME_TRANSCRIPTION_PROVIDER="openai",
    RAGTIME_TRANSCRIPTION_API_KEY="test-key",
    RAGTIME_TRANSCRIPTION_MODEL="whisper-1",
)
class TranscribeEpisodeTests(TestCase):
    """Tests for the transcribe_episode task function."""

    def _create_episode_with_audio(self, **kwargs):
        from django.core.files.base import ContentFile

        with patch("episodes.signals.async_task"):
            episode = Episode.objects.create(**kwargs)
            episode.audio_file.save(
                f"{episode.pk}.mp3",
                ContentFile(b"fake-audio-data" * 100),
                save=True,
            )
        return episode

    def _create_episode(self, **kwargs):
        with patch("episodes.signals.async_task"):
            return Episode.objects.create(**kwargs)

    @patch("episodes.transcriber.get_transcription_provider")
    def test_success(self, mock_factory):
        from episodes.transcriber import transcribe_episode

        mock_provider = MagicMock()
        mock_provider.transcribe.return_value = SAMPLE_WHISPER_RESPONSE
        mock_factory.return_value = mock_provider

        episode = self._create_episode_with_audio(
            url="https://example.com/ep/tr-1",
            status=Episode.Status.TRANSCRIBING,
        )

        with patch("episodes.signals.async_task"):
            transcribe_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.SUMMARIZING)
        self.assertEqual(episode.transcript, "Hello, welcome to the jazz podcast.")
        self.assertEqual(episode.transcript_json, SAMPLE_WHISPER_RESPONSE)

    @patch("episodes.transcriber.get_transcription_provider")
    def test_no_audio_file_fails(self, mock_factory):
        from episodes.transcriber import transcribe_episode

        episode = self._create_episode(
            url="https://example.com/ep/tr-2",
            status=Episode.Status.TRANSCRIBING,
        )

        with patch("episodes.signals.async_task"):
            transcribe_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("No audio file", episode.error_message)
        mock_factory.assert_not_called()

    @patch("episodes.transcriber.get_transcription_provider")
    def test_api_error_sets_failed(self, mock_factory):
        from episodes.transcriber import transcribe_episode

        mock_provider = MagicMock()
        mock_provider.transcribe.side_effect = Exception("API rate limit exceeded")
        mock_factory.return_value = mock_provider

        episode = self._create_episode_with_audio(
            url="https://example.com/ep/tr-3",
            status=Episode.Status.TRANSCRIBING,
        )

        with patch("episodes.signals.async_task"):
            transcribe_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("API rate limit exceeded", episode.error_message)

    def test_nonexistent_episode(self):
        from episodes.transcriber import transcribe_episode

        transcribe_episode(99999)  # should not raise

    def test_wrong_status_skips(self):
        from episodes.transcriber import transcribe_episode

        episode = self._create_episode(
            url="https://example.com/ep/tr-4",
            status=Episode.Status.PENDING,
        )

        transcribe_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.PENDING)

    @patch("episodes.transcriber.get_transcription_provider")
    def test_empty_language_passes_none(self, mock_factory):
        from episodes.transcriber import transcribe_episode

        mock_provider = MagicMock()
        mock_provider.transcribe.return_value = SAMPLE_WHISPER_RESPONSE
        mock_factory.return_value = mock_provider

        episode = self._create_episode_with_audio(
            url="https://example.com/ep/tr-5",
            language="",
            status=Episode.Status.TRANSCRIBING,
        )

        with patch("episodes.signals.async_task"):
            transcribe_episode(episode.pk)

        mock_provider.transcribe.assert_called_once()
        _, kwargs = mock_provider.transcribe.call_args
        self.assertIsNone(kwargs["language"])

    @patch("episodes.transcriber.get_transcription_provider")
    def test_language_passed_to_provider(self, mock_factory):
        from episodes.transcriber import transcribe_episode

        mock_provider = MagicMock()
        mock_provider.transcribe.return_value = SAMPLE_WHISPER_RESPONSE
        mock_factory.return_value = mock_provider

        episode = self._create_episode_with_audio(
            url="https://example.com/ep/tr-6",
            language="en",
            status=Episode.Status.TRANSCRIBING,
        )

        with patch("episodes.signals.async_task"):
            transcribe_episode(episode.pk)

        mock_provider.transcribe.assert_called_once()
        _, kwargs = mock_provider.transcribe.call_args
        self.assertEqual(kwargs["language"], "en")


class TranscribeSignalTests(TestCase):
    @patch("episodes.signals.async_task")
    def test_status_change_to_transcribing_queues_transcribe(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/sig-tr-1")
        mock_async.reset_mock()

        episode.status = Episode.Status.TRANSCRIBING
        episode.save(update_fields=["status", "updated_at"])

        mock_async.assert_called_once_with(
            "episodes.transcriber.transcribe_episode", episode.pk
        )
