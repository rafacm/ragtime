from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from episodes.models import Episode

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
