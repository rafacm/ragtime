from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from episodes.models import Episode


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
