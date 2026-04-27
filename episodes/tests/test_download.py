import subprocess
from unittest.mock import patch

from django.test import TestCase

from episodes.models import Episode


class DownloadEpisodeTests(TestCase):
    """Tests for the download_episode task function."""

    def _create_episode(self, **kwargs):
        with patch("episodes.signals.DBOS"):
            return Episode.objects.create(**kwargs)

    @patch("episodes.downloader.MP3")
    @patch("episodes.downloader.subprocess.run")
    def test_success_small_file(self, mock_run, mock_mp3):
        """Download → status transcribing."""
        from episodes.downloader import download_episode

        audio_data = b"fake-mp3-data" * 100  # small file
        mock_mp3.return_value.info.length = 3661.5

        def write_fake_audio(cmd, **kwargs):
            # cmd is ["wget", "-q", "-O", tmp_path, url]
            with open(cmd[3], "wb") as f:
                f.write(audio_data)

        mock_run.side_effect = write_fake_audio

        episode = self._create_episode(
            url="https://example.com/ep/dl-1",
            audio_url="https://example.com/ep1.mp3",
            status=Episode.Status.DOWNLOADING,
        )

        with patch("episodes.signals.DBOS"):
            download_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.TRANSCRIBING)
        self.assertTrue(episode.audio_file)
        self.assertEqual(episode.duration, 3661)

    @patch("episodes.downloader.MP3")
    @patch("episodes.downloader.subprocess.run")
    def test_large_file_still_goes_to_transcribing(self, mock_run, mock_mp3):
        """Download of large file → status transcribing (resize happens in transcribe step)."""
        from episodes.downloader import download_episode

        audio_data = b"x" * 200
        mock_mp3.return_value.info.length = 120.0

        def write_fake_audio(cmd, **kwargs):
            with open(cmd[3], "wb") as f:
                f.write(audio_data)

        mock_run.side_effect = write_fake_audio

        episode = self._create_episode(
            url="https://example.com/ep/dl-2",
            audio_url="https://example.com/ep2.mp3",
            status=Episode.Status.DOWNLOADING,
        )

        with patch("episodes.signals.DBOS"):
            download_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.TRANSCRIBING)

    @patch("episodes.downloader.subprocess.run")
    def test_wget_error_sets_failed(self, mock_run):
        """wget error → status failed with error_message."""
        from episodes.downloader import download_episode

        mock_run.side_effect = subprocess.CalledProcessError(8, "wget")

        episode = self._create_episode(
            url="https://example.com/ep/dl-3",
            audio_url="https://example.com/ep3.mp3",
            status=Episode.Status.DOWNLOADING,
        )

        with patch("episodes.signals.DBOS"):
            download_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("wget", episode.error_message)

    def test_nonexistent_episode(self):
        """Non-existent episode ID → no crash."""
        from episodes.downloader import download_episode

        download_episode(99999)  # should not raise

    def test_wrong_status_skips(self):
        """Episode not in 'downloading' status → skip."""
        from episodes.downloader import download_episode

        episode = self._create_episode(
            url="https://example.com/ep/dl-4",
            status=Episode.Status.QUEUED,
        )

        download_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.QUEUED)
