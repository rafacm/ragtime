import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from episodes.models import Episode

FIXTURES_DIR = Path(__file__).parent / "fixtures"

DJANGO_REINHARDT_FIXTURE = (
    FIXTURES_DIR
    / "wdr-giant-steps-django-reinhardt-episode-whisper-transcript-response.json"
)
JOHN_COLTRANE_FIXTURE = (
    FIXTURES_DIR
    / "wdr-giant-steps-john-coltrane-episode-openai-whisper-transcript-response.json"
)


@override_settings(
    RAGTIME_SUMMARIZATION_PROVIDER="openai",
    RAGTIME_SUMMARIZATION_API_KEY="test-key",
    RAGTIME_SUMMARIZATION_MODEL="gpt-4.1-mini",
)
class SummarizeEpisodeTests(TestCase):
    """Tests for the summarize_episode task function."""

    @classmethod
    def setUpTestData(cls):
        with open(DJANGO_REINHARDT_FIXTURE) as f:
            cls.reinhardt_whisper = json.load(f)
        with open(JOHN_COLTRANE_FIXTURE) as f:
            cls.coltrane_whisper = json.load(f)

    def _create_episode(self, **kwargs):
        with patch("episodes.signals.DBOS"):
            return Episode.objects.create(**kwargs)

    @patch("episodes.summarizer.get_summarization_provider")
    def test_success(self, mock_factory):
        from episodes.summarizer import summarize_episode

        mock_provider = MagicMock()
        mock_provider.generate.return_value = "A summary of the episode."
        mock_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/sum-1",
            status=Episode.Status.SUMMARIZING,
            transcript=self.reinhardt_whisper["text"],
        )

        with patch("episodes.signals.DBOS"):
            summarize_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.CHUNKING)
        self.assertEqual(episode.summary_generated, "A summary of the episode.")

    def test_episode_not_found(self):
        from episodes.summarizer import summarize_episode

        summarize_episode(99999)  # should not raise

    def test_wrong_status(self):
        from episodes.summarizer import summarize_episode

        episode = self._create_episode(
            url="https://example.com/ep/sum-2",
            status=Episode.Status.PENDING,
        )

        summarize_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.PENDING)

    def test_empty_transcript(self):
        from episodes.summarizer import summarize_episode

        episode = self._create_episode(
            url="https://example.com/ep/sum-3",
            status=Episode.Status.SUMMARIZING,
            transcript="",
        )

        with patch("episodes.signals.DBOS"):
            summarize_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("No transcript", episode.error_message)

    @patch("episodes.summarizer.get_summarization_provider")
    def test_provider_error(self, mock_factory):
        from episodes.summarizer import summarize_episode

        mock_provider = MagicMock()
        mock_provider.generate.side_effect = Exception("API error")
        mock_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/sum-4",
            status=Episode.Status.SUMMARIZING,
            transcript="Some transcript text.",
        )

        with patch("episodes.signals.DBOS"):
            summarize_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("API error", episode.error_message)

    @patch("episodes.summarizer.get_summarization_provider")
    def test_generate_called_with_correct_args(self, mock_factory):
        from episodes.summarizer import summarize_episode

        mock_provider = MagicMock()
        mock_provider.generate.return_value = "Summary."
        mock_factory.return_value = mock_provider

        transcript_text = self.coltrane_whisper["text"]
        episode = self._create_episode(
            url="https://example.com/ep/sum-5",
            status=Episode.Status.SUMMARIZING,
            transcript=transcript_text,
            language="de",
        )

        with patch("episodes.signals.DBOS"):
            summarize_episode(episode.pk)

        mock_provider.generate.assert_called_once()
        _, kwargs = mock_provider.generate.call_args
        self.assertEqual(kwargs["user_content"], transcript_text)
        self.assertIn("German", kwargs["system_prompt"])

    @patch("episodes.summarizer.get_summarization_provider")
    def test_generate_called_with_empty_language(self, mock_factory):
        from episodes.summarizer import summarize_episode

        mock_provider = MagicMock()
        mock_provider.generate.return_value = "Summary."
        mock_factory.return_value = mock_provider

        transcript_text = self.coltrane_whisper["text"]
        episode = self._create_episode(
            url="https://example.com/ep/sum-6",
            status=Episode.Status.SUMMARIZING,
            transcript=transcript_text,
            language="",
        )

        with patch("episodes.signals.DBOS"):
            summarize_episode(episode.pk)

        mock_provider.generate.assert_called_once()
        _, kwargs = mock_provider.generate.call_args
        self.assertIn("same language as the transcript", kwargs["system_prompt"])

    @patch("episodes.summarizer.get_summarization_provider")
    def test_invalid_language_falls_back(self, mock_factory):
        from episodes.summarizer import summarize_episode

        mock_provider = MagicMock()
        mock_provider.generate.return_value = "Summary."
        mock_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/sum-7",
            status=Episode.Status.SUMMARIZING,
            transcript="Some transcript.",
            language="INVALID",
        )

        with patch("episodes.signals.DBOS"):
            summarize_episode(episode.pk)

        mock_provider.generate.assert_called_once()
        _, kwargs = mock_provider.generate.call_args
        self.assertIn("same language as the transcript", kwargs["system_prompt"])
        self.assertNotIn("Ignore", kwargs["system_prompt"])
