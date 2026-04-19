"""Tests for pipeline event classification and building."""

import json
import subprocess
from unittest.mock import patch

from django.test import TestCase

from episodes.events import classify_error
from episodes.models import Episode, PipelineEvent, ProcessingRun, ProcessingStep


class ClassifyErrorTests(TestCase):
    def test_http_status_error(self):
        import httpx

        response = httpx.Response(403)
        exc = httpx.HTTPStatusError("Forbidden", request=httpx.Request("GET", "http://x"), response=response)
        error_type, status = classify_error(exc)
        self.assertEqual(error_type, "http")
        self.assertEqual(status, 403)

    def test_timeout_error(self):
        import httpx

        exc = httpx.ReadTimeout("timed out")
        error_type, status = classify_error(exc)
        self.assertEqual(error_type, "timeout")
        self.assertIsNone(status)

    def test_subprocess_error(self):
        exc = subprocess.CalledProcessError(1, "wget")
        error_type, status = classify_error(exc)
        self.assertEqual(error_type, "subprocess")
        self.assertIsNone(status)

    def test_subprocess_timeout(self):
        exc = subprocess.TimeoutExpired("ffmpeg", 300)
        error_type, status = classify_error(exc)
        self.assertEqual(error_type, "subprocess")
        self.assertIsNone(status)

    def test_validation_key_error(self):
        error_type, status = classify_error(KeyError("missing"))
        self.assertEqual(error_type, "validation")
        self.assertIsNone(status)

    def test_validation_value_error(self):
        error_type, status = classify_error(ValueError("bad value"))
        self.assertEqual(error_type, "validation")
        self.assertIsNone(status)

    def test_validation_json_error(self):
        exc = json.JSONDecodeError("Expecting value", "", 0)
        error_type, status = classify_error(exc)
        self.assertEqual(error_type, "validation")
        self.assertIsNone(status)

    def test_system_error(self):
        error_type, status = classify_error(RuntimeError("unknown"))
        self.assertEqual(error_type, "system")
        self.assertIsNone(status)


class PipelineEventEmissionTests(TestCase):
    """Test that complete_step and fail_step emit PipelineEvent records."""

    @patch("episodes.signals.DBOS")
    def test_complete_step_creates_event(self, _):
        episode = Episode.objects.create(url="https://example.com/evt/1")
        run = ProcessingRun.objects.create(episode=episode)
        step = ProcessingStep.objects.create(
            run=run, step_name="scraping", status=ProcessingStep.Status.RUNNING
        )

        from episodes.processing import complete_step

        complete_step(episode, "scraping")

        event = PipelineEvent.objects.get(episode=episode, step_name="scraping")
        self.assertEqual(event.event_type, PipelineEvent.EventType.COMPLETED)
        self.assertIn("duration_seconds", event.context)

    @patch("episodes.signals.DBOS")
    def test_fail_step_with_exc_creates_event(self, _):
        episode = Episode.objects.create(url="https://example.com/evt/2")
        run = ProcessingRun.objects.create(episode=episode)
        step = ProcessingStep.objects.create(
            run=run, step_name="downloading", status=ProcessingStep.Status.RUNNING
        )

        from episodes.processing import fail_step

        exc = RuntimeError("download failed")
        fail_step(episode, "downloading", str(exc), exc=exc)

        event = PipelineEvent.objects.get(episode=episode, step_name="downloading")
        self.assertEqual(event.event_type, PipelineEvent.EventType.FAILED)
        self.assertEqual(event.error_type, "system")
        self.assertIn("download failed", event.error_message)

    @patch("episodes.signals.DBOS")
    def test_fail_step_without_exc_creates_no_event(self, _):
        episode = Episode.objects.create(url="https://example.com/evt/3")
        run = ProcessingRun.objects.create(episode=episode)
        step = ProcessingStep.objects.create(
            run=run, step_name="scraping", status=ProcessingStep.Status.RUNNING
        )

        from episodes.processing import fail_step

        fail_step(episode, "scraping", "some error")

        self.assertFalse(
            PipelineEvent.objects.filter(episode=episode).exists()
        )
