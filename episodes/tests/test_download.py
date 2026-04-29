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

    @patch("episodes.agents.download.run_download_agent")
    @patch("episodes.downloader.subprocess.run")
    def test_wget_error_falls_through_to_agent(self, mock_run, mock_agent):
        """wget failure → agent fallback → DownloadFailed when the agent also gives up.

        Mocks ``run_download_agent`` so the test doesn't try to launch a real
        Playwright browser (CI has no chromium installed).
        """
        from episodes.agents.download_deps import DownloadAgentResult
        from episodes.downloader import download_episode

        mock_run.side_effect = subprocess.CalledProcessError(8, "wget")
        mock_agent.return_value = DownloadAgentResult(
            success=False,
            message="agent could not find audio",
        )

        episode = self._create_episode(
            url="https://example.com/ep/dl-3",
            audio_url="https://example.com/ep3.mp3",
            status=Episode.Status.DOWNLOADING,
        )

        with patch("episodes.signals.DBOS"):
            download_episode(episode.pk)

        # Agent was invoked exactly once with the episode's context.
        mock_agent.assert_called_once()

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        # Both tiers recorded in sources_tried; the original wget exit code
        # is preserved in wget_error inside the DownloadFailed payload.
        self.assertIn("wget", episode.error_message)
        self.assertIn("agent", episode.error_message)

    @patch("episodes.agents.download.run_download_agent")
    @patch("episodes.downloader.MP3")
    @patch("episodes.downloader.subprocess.run")
    def test_agent_recovers_after_wget_fails(self, mock_run, mock_mp3, mock_agent):
        """wget failure → agent succeeds → status transcribing."""
        import os
        import tempfile

        from episodes.agents.download_deps import DownloadAgentResult
        from episodes.downloader import download_episode

        mock_run.side_effect = subprocess.CalledProcessError(8, "wget")
        mock_mp3.return_value.info.length = 1234.0

        # Stage a fake downloaded file the orchestrator will attach.
        fd, agent_file = tempfile.mkstemp(suffix=".mp3", prefix="ragtime-test-")
        os.write(fd, b"fake-mp3-data" * 100)
        os.close(fd)
        try:
            mock_agent.return_value = DownloadAgentResult(
                success=True,
                source="fyyd",
                audio_url="https://cdn.example/ep4.mp3",
                downloaded_file=agent_file,
            )

            episode = self._create_episode(
                url="https://example.com/ep/dl-4",
                audio_url="https://example.com/ep4.mp3",
                status=Episode.Status.DOWNLOADING,
            )

            with patch("episodes.signals.DBOS"):
                download_episode(episode.pk)

            episode.refresh_from_db()
            self.assertEqual(episode.status, Episode.Status.TRANSCRIBING)
            self.assertTrue(episode.audio_file)
            self.assertEqual(episode.duration, 1234)
            # Stale URL was overwritten with the agent-discovered enclosure
            # so a future reprocess won't waste a wget hop on the bad URL.
            self.assertEqual(episode.audio_url, "https://cdn.example/ep4.mp3")
        finally:
            # _save_audio moved the file out of agent_file; cleanup is a
            # best-effort no-op once the orchestrator has attached it.
            try:
                os.unlink(agent_file)
            except OSError:
                pass

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
