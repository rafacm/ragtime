from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from episodes.models import Episode


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
