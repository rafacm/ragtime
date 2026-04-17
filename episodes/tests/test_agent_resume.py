"""Tests for pipeline resume logic after agent recovery."""

import os
import tempfile
from unittest.mock import patch

from django.test import TestCase

from episodes.agents.deps import RecoveryAgentResult
from episodes.agents.resume import resume_pipeline

from episodes.events import StepFailureEvent
from episodes.models import Episode, ProcessingRun, ProcessingStep


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
    @patch("episodes.signals.async_task")
    def test_sets_audio_url_and_creates_run(self, _mock_task):
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

        # A new ProcessingRun should exist, resumed from downloading
        run = ProcessingRun.objects.filter(episode=episode).order_by("-started_at").first()
        self.assertIsNotNone(run)
        self.assertEqual(run.resumed_from_step, Episode.Status.DOWNLOADING)

        # Scraping step should be SKIPPED, downloading should be PENDING
        steps = {s.step_name: s.status for s in run.steps.all()}
        self.assertEqual(steps["scraping"], ProcessingStep.Status.SKIPPED)
        self.assertEqual(steps["downloading"], ProcessingStep.Status.PENDING)


    @patch("episodes.signals.async_task")
    @patch("episodes.agents.resume.MP3")
    def test_skips_download_when_file_already_downloaded(self, mock_mp3, _mock_task):
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

            # Run should resume from transcribing, not downloading
            run = ProcessingRun.objects.filter(
                episode=episode
            ).order_by("-started_at").first()
            self.assertIsNotNone(run)
            self.assertEqual(run.resumed_from_step, Episode.Status.TRANSCRIBING)

            steps = {s.step_name: s.status for s in run.steps.all()}
            self.assertEqual(steps["scraping"], ProcessingStep.Status.SKIPPED)
            self.assertEqual(steps["downloading"], ProcessingStep.Status.SKIPPED)
            self.assertEqual(steps["transcribing"], ProcessingStep.Status.PENDING)
        finally:
            if episode.audio_file:
                try:
                    os.unlink(episode.audio_file.path)
                except OSError:
                    pass


class ResumePipelineDownloadingTests(TestCase):
    @patch("episodes.signals.async_task")
    @patch("episodes.agents.resume.MP3")
    def test_saves_file_and_creates_run(self, mock_mp3, _mock_task):
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

            # A new ProcessingRun resumed from transcribing
            run = ProcessingRun.objects.filter(
                episode=episode
            ).order_by("-started_at").first()
            self.assertIsNotNone(run)
            self.assertEqual(run.resumed_from_step, Episode.Status.TRANSCRIBING)

            steps = {s.step_name: s.status for s in run.steps.all()}
            self.assertEqual(steps["scraping"], ProcessingStep.Status.SKIPPED)
            self.assertEqual(steps["downloading"], ProcessingStep.Status.SKIPPED)
            self.assertEqual(steps["transcribing"], ProcessingStep.Status.PENDING)
        finally:
            # Clean up saved audio file
            if episode.audio_file:
                try:
                    os.unlink(episode.audio_file.path)
                except OSError:
                    pass
