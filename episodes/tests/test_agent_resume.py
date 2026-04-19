"""Tests for pipeline resume logic after agent recovery."""

import os
import tempfile
from unittest.mock import patch

from django.test import TestCase

from episodes.agents.deps import RecoveryAgentResult
from episodes.agents.resume import resume_pipeline

from episodes.events import StepFailureEvent
from episodes.models import Episode


def _make_failure_event(**overrides):
    from django.utils import timezone

    defaults = {
        "episode_id": 1,
        "step_name": "scraping",
        "processing_run_id": 1,
        "processing_step_id": 1,
        "error_type": "http",
        "error_message": "403 Forbidden",
        "http_status": 403,
        "exception_class": "httpx.HTTPStatusError",
        "attempt_number": 1,
        "cached_data": {},
        "timestamp": timezone.now(),
    }
    defaults.update(overrides)
    return StepFailureEvent(**defaults)


class ResumePipelineScrapingTests(TestCase):
    @patch("episodes.signals.DBOS")
    @patch("episodes.agents.resume.DBOS")
    def test_sets_audio_url_and_starts_workflow(self, mock_dbos, _):
        episode = Episode.objects.create(
            url="https://example.com/pod/1",
            status=Episode.Status.FAILED,
        )
        event = _make_failure_event(
            episode_id=episode.pk, step_name="scraping"
        )
        result = RecoveryAgentResult(
            success=True,
            audio_url="https://cdn.example.com/episode1.mp3",
            message="Found audio URL",
        )

        resume_pipeline(event, result)

        episode.refresh_from_db()
        self.assertEqual(episode.audio_url, "https://cdn.example.com/episode1.mp3")
        self.assertEqual(episode.status, Episode.Status.DOWNLOADING)
        self.assertEqual(episode.error_message, "")

        from episodes.workflows import process_episode

        mock_dbos.start_workflow.assert_called_once_with(
            process_episode, episode.pk, Episode.Status.DOWNLOADING,
        )

    @patch("episodes.signals.DBOS")
    @patch("episodes.agents.resume.DBOS")
    @patch("episodes.agents.resume.MP3")
    def test_skips_download_when_file_already_downloaded(self, mock_mp3, mock_dbos, _):
        """When scraping recovery also downloaded the file, skip to transcribing."""
        episode = Episode.objects.create(
            url="https://example.com/pod/skip-dl",
            status=Episode.Status.FAILED,
        )

        mock_mp3_instance = mock_mp3.return_value
        mock_mp3_instance.info.length = 1800  # 30 min

        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        try:
            tmp.write(b"\x00" * 1024)
            tmp.close()

            event = _make_failure_event(
                episode_id=episode.pk, step_name="scraping"
            )
            result = RecoveryAgentResult(
                success=True,
                audio_url="https://cdn.example.com/episode-skip.mp3",
                downloaded_file=tmp.name,
                message="Found audio URL and downloaded file",
            )

            resume_pipeline(event, result)

            episode.refresh_from_db()
            self.assertEqual(episode.audio_url, "https://cdn.example.com/episode-skip.mp3")
            self.assertEqual(episode.status, Episode.Status.TRANSCRIBING)
            self.assertTrue(episode.audio_file)
            self.assertEqual(episode.duration, 1800)
            self.assertEqual(episode.error_message, "")

            # Temp file should be cleaned up
            self.assertFalse(os.path.exists(tmp.name))

            from episodes.workflows import process_episode

            mock_dbos.start_workflow.assert_called_once_with(
                process_episode, episode.pk, Episode.Status.TRANSCRIBING,
            )
        finally:
            if episode.audio_file:
                try:
                    os.unlink(episode.audio_file.path)
                except OSError:
                    pass


class ResumePipelineDownloadingTests(TestCase):
    @patch("episodes.signals.DBOS")
    @patch("episodes.agents.resume.DBOS")
    @patch("episodes.agents.resume.MP3")
    def test_saves_file_and_starts_workflow(self, mock_mp3, mock_dbos, _):
        episode = Episode.objects.create(
            url="https://example.com/pod/2",
            audio_url="https://cdn.example.com/ep2.mp3",
            status=Episode.Status.FAILED,
        )

        # Mock MP3 duration extraction
        mock_mp3_instance = mock_mp3.return_value
        mock_mp3_instance.info.length = 3600  # 1 hour

        # Create a temp file to act as the downloaded audio
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        try:
            tmp.write(b"\x00" * 1024)
            tmp.close()

            event = _make_failure_event(
                episode_id=episode.pk, step_name="downloading"
            )
            result = RecoveryAgentResult(
                success=True,
                downloaded_file=tmp.name,
                message="Downloaded via browser",
            )

            resume_pipeline(event, result)

            episode.refresh_from_db()
            self.assertEqual(episode.status, Episode.Status.TRANSCRIBING)
            self.assertTrue(episode.audio_file)
            self.assertEqual(episode.duration, 3600)
            self.assertEqual(episode.error_message, "")

            # Temp file should be cleaned up by resume_pipeline
            self.assertFalse(os.path.exists(tmp.name))

            from episodes.workflows import process_episode

            mock_dbos.start_workflow.assert_called_once_with(
                process_episode, episode.pk, Episode.Status.TRANSCRIBING,
            )
        finally:
            # Clean up saved audio file
            if episode.audio_file:
                try:
                    os.unlink(episode.audio_file.path)
                except OSError:
                    pass
