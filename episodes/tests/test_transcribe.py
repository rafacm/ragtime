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

        with patch("episodes.signals.DBOS"):
            episode = Episode.objects.create(**kwargs)
            episode.audio_file.save(
                f"{episode.pk}.mp3",
                ContentFile(b"fake-audio-data" * 100),
                save=True,
            )
        return episode

    def _create_episode(self, **kwargs):
        with patch("episodes.signals.DBOS"):
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

        with patch("episodes.signals.DBOS"):
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

        with patch("episodes.signals.DBOS"):
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

        with patch("episodes.signals.DBOS"):
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
            status=Episode.Status.QUEUED,
        )

        transcribe_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.QUEUED)

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

        with patch("episodes.signals.DBOS"):
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

        with patch("episodes.signals.DBOS"):
            transcribe_episode(episode.pk)

        mock_provider.transcribe.assert_called_once()
        _, kwargs = mock_provider.transcribe.call_args
        self.assertEqual(kwargs["language"], "en")


@override_settings(
    RAGTIME_TRANSCRIPTION_PROVIDER="openai",
    RAGTIME_TRANSCRIPTION_API_KEY="test-key",
    RAGTIME_TRANSCRIPTION_MODEL="whisper-1",
)
class ResizeWithinTranscribeTests(TestCase):
    """Tests for the resize logic embedded in transcribe_episode."""

    def _create_episode_with_audio(self, audio_size=100, **kwargs):
        from django.core.files.base import ContentFile

        with patch("episodes.signals.DBOS"):
            episode = Episode.objects.create(**kwargs)
            episode.audio_file.save(
                f"{episode.pk}.mp3",
                ContentFile(b"x" * audio_size),
                save=True,
            )
        return episode

    @patch("episodes.transcriber.get_transcription_provider")
    @override_settings(RAGTIME_MAX_AUDIO_SIZE=25 * 1024 * 1024)
    def test_small_file_skips_resize(self, mock_factory):
        """File under max size → no resize, transcription proceeds."""
        from episodes.transcriber import transcribe_episode

        mock_provider = MagicMock()
        mock_provider.transcribe.return_value = SAMPLE_WHISPER_RESPONSE
        mock_factory.return_value = mock_provider

        episode = self._create_episode_with_audio(
            audio_size=100,
            url="https://example.com/ep/rtr-1",
            status=Episode.Status.TRANSCRIBING,
        )

        with patch("episodes.signals.DBOS"):
            transcribe_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.SUMMARIZING)

    @patch("episodes.transcriber.get_transcription_provider")
    @patch("episodes.transcriber.subprocess.run")
    @patch("episodes.transcriber.shutil.which", return_value="/usr/bin/ffmpeg")
    @override_settings(RAGTIME_MAX_AUDIO_SIZE=50)
    def test_large_file_resized(self, mock_which, mock_run, mock_factory):
        """File over max size → ffmpeg resize, then transcription."""
        from episodes.transcriber import transcribe_episode

        mock_provider = MagicMock()
        mock_provider.transcribe.return_value = SAMPLE_WHISPER_RESPONSE
        mock_factory.return_value = mock_provider

        def fake_ffmpeg(args, **kw):
            output_path = args[-1]
            with open(output_path, "wb") as f:
                f.write(b"small" * 5)  # 25 bytes, under 50 limit
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        episode = self._create_episode_with_audio(
            audio_size=200,
            url="https://example.com/ep/rtr-2",
            status=Episode.Status.TRANSCRIBING,
        )

        with patch("episodes.signals.DBOS"):
            transcribe_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.SUMMARIZING)
        mock_run.assert_called_once()

    @patch("episodes.transcriber.get_transcription_provider")
    @patch("episodes.transcriber.subprocess.run")
    @patch("episodes.transcriber.shutil.which", return_value="/usr/bin/ffmpeg")
    @override_settings(RAGTIME_MAX_AUDIO_SIZE=50)
    def test_still_too_large_after_resize(self, mock_which, mock_run, mock_factory):
        """Resized file still over max after all tiers → status failed."""
        from episodes.transcriber import transcribe_episode

        def fake_ffmpeg(args, **kw):
            output_path = args[-1]
            with open(output_path, "wb") as f:
                f.write(b"x" * 200)  # still too large for every tier
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        episode = self._create_episode_with_audio(
            audio_size=200,
            url="https://example.com/ep/rtr-3",
            status=Episode.Status.TRANSCRIBING,
        )

        with patch("episodes.signals.DBOS"):
            transcribe_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("limit after resizing", episode.error_message)

    @patch("episodes.transcriber.get_transcription_provider")
    @patch("episodes.transcriber.shutil.which", return_value=None)
    @override_settings(RAGTIME_MAX_AUDIO_SIZE=50)
    def test_no_ffmpeg_fails(self, mock_which, mock_factory):
        """ffmpeg not on PATH → status failed."""
        from episodes.transcriber import transcribe_episode

        episode = self._create_episode_with_audio(
            audio_size=200,
            url="https://example.com/ep/rtr-4",
            status=Episode.Status.TRANSCRIBING,
        )

        with patch("episodes.signals.DBOS"):
            transcribe_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("ffmpeg is not installed", episode.error_message)

    @patch("episodes.transcriber.get_transcription_provider")
    @patch("episodes.transcriber.subprocess.run")
    @patch("episodes.transcriber.shutil.which", return_value="/usr/bin/ffmpeg")
    @override_settings(RAGTIME_MAX_AUDIO_SIZE=50)
    def test_ffmpeg_error_fails(self, mock_which, mock_run, mock_factory):
        """ffmpeg returns non-zero → status failed."""
        from episodes.transcriber import transcribe_episode

        mock_run.return_value = MagicMock(
            returncode=1, stderr=b"Invalid input file"
        )

        episode = self._create_episode_with_audio(
            audio_size=200,
            url="https://example.com/ep/rtr-5",
            status=Episode.Status.TRANSCRIBING,
        )

        with patch("episodes.signals.DBOS"):
            transcribe_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("ffmpeg failed", episode.error_message)

    @patch("episodes.transcriber.get_transcription_provider")
    @patch("episodes.transcriber.subprocess.run")
    @patch("episodes.transcriber.shutil.which", return_value="/usr/bin/ffmpeg")
    @override_settings(RAGTIME_MAX_AUDIO_SIZE=200_000)
    def test_duration_selects_gentle_tier(self, mock_which, mock_run, mock_factory):
        """Episode with short duration selects high-quality tier (128k)."""
        from episodes.transcriber import transcribe_episode

        mock_provider = MagicMock()
        mock_provider.transcribe.return_value = SAMPLE_WHISPER_RESPONSE
        mock_factory.return_value = mock_provider

        def fake_ffmpeg(args, **kw):
            output_path = args[-1]
            with open(output_path, "wb") as f:
                f.write(b"x" * 100)
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        # 10s at 128kbps * 1.10 = 176,000 bytes, under 200,000 limit → tier 0
        episode = self._create_episode_with_audio(
            audio_size=300_000,
            url="https://example.com/ep/rtr-6",
            status=Episode.Status.TRANSCRIBING,
            duration=10,
        )

        with patch("episodes.signals.DBOS"):
            transcribe_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.SUMMARIZING)
        ffmpeg_args = mock_run.call_args[0][0]
        self.assertIn("128k", ffmpeg_args)
        self.assertIn("44100", ffmpeg_args)

    @patch("episodes.transcriber.get_transcription_provider")
    @patch("episodes.transcriber.subprocess.run")
    @patch("episodes.transcriber.shutil.which", return_value="/usr/bin/ffmpeg")
    @override_settings(RAGTIME_MAX_AUDIO_SIZE=200_000)
    def test_retry_with_lower_tier_on_oversize(self, mock_which, mock_run, mock_factory):
        """First tier output too large → retries with next tier until it fits."""
        from episodes.transcriber import transcribe_episode

        mock_provider = MagicMock()
        mock_provider.transcribe.return_value = SAMPLE_WHISPER_RESPONSE
        mock_factory.return_value = mock_provider

        call_count = 0

        def fake_ffmpeg(args, **kw):
            nonlocal call_count
            call_count += 1
            output_path = args[-1]
            with open(output_path, "wb") as f:
                # First call: still too large; second call: fits
                f.write(b"x" * (300_000 if call_count == 1 else 100))
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        # 10s at 128kbps * 1.10 = 176,000 bytes → starts at tier 0
        episode = self._create_episode_with_audio(
            audio_size=300_000,
            url="https://example.com/ep/rtr-8",
            status=Episode.Status.TRANSCRIBING,
            duration=10,
        )

        with patch("episodes.signals.DBOS"):
            transcribe_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.SUMMARIZING)
        self.assertEqual(mock_run.call_count, 2)
        # Second call should use tier 1 (96k)
        second_call_args = mock_run.call_args_list[1][0][0]
        self.assertIn("96k", second_call_args)

    @patch("episodes.transcriber.get_transcription_provider")
    @patch("episodes.transcriber.subprocess.run")
    @patch("episodes.transcriber.shutil.which", return_value="/usr/bin/ffmpeg")
    @override_settings(RAGTIME_MAX_AUDIO_SIZE=50)
    def test_no_duration_uses_most_aggressive(self, mock_which, mock_run, mock_factory):
        """Episode without duration falls back to tier 4 (32k)."""
        from episodes.transcriber import transcribe_episode

        mock_provider = MagicMock()
        mock_provider.transcribe.return_value = SAMPLE_WHISPER_RESPONSE
        mock_factory.return_value = mock_provider

        def fake_ffmpeg(args, **kw):
            output_path = args[-1]
            with open(output_path, "wb") as f:
                f.write(b"small" * 5)
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        episode = self._create_episode_with_audio(
            audio_size=200,
            url="https://example.com/ep/rtr-7",
            status=Episode.Status.TRANSCRIBING,
            # no duration set
        )

        with patch("episodes.signals.DBOS"):
            transcribe_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.SUMMARIZING)
        ffmpeg_args = mock_run.call_args[0][0]
        self.assertIn("32k", ffmpeg_args)
        self.assertIn("16000", ffmpeg_args)


class ResizeTierSelectionTests(TestCase):
    """Pure unit tests for _select_resize_tier."""

    def test_short_episode_picks_tier_0(self):
        from episodes.transcriber import _select_resize_tier

        # 600s at 128kbps * 1.10 = ~10.56MB, well under 25MB
        max_size = 25 * 1024 * 1024
        self.assertEqual(_select_resize_tier(600, max_size), 0)

    def test_medium_episode_picks_lower_tier(self):
        from episodes.transcriber import _select_resize_tier

        # 3600s at 128kbps * 1.10 = ~63.4MB > 25MB → not tier 0
        # 3600s at 96kbps * 1.10 = ~47.5MB > 25MB → not tier 1
        # 3600s at 64kbps * 1.10 = ~31.7MB > 25MB → not tier 2
        # 3600s at 48kbps * 1.10 = ~23.8MB < 25MB → tier 3
        max_size = 25 * 1024 * 1024
        self.assertEqual(_select_resize_tier(3600, max_size), 3)

    def test_very_long_episode_returns_none(self):
        from episodes.transcriber import _select_resize_tier

        # 20000s at 32kbps * 1.10 = ~88MB > 25MB → no tier fits
        max_size = 25 * 1024 * 1024
        self.assertIsNone(_select_resize_tier(20000, max_size))

    def test_none_duration_returns_last_tier(self):
        from episodes.transcriber import _select_resize_tier

        max_size = 25 * 1024 * 1024
        self.assertEqual(_select_resize_tier(None, max_size), 4)
