"""Tests for ``manage.py submit_episode``."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from episodes.models import Episode


class SubmitEpisodeTests(TestCase):
    def setUp(self):
        # Patch the pipeline queue so creating an Episode doesn't require a
        # live DBOS runtime.
        patcher = patch("episodes.workflows.episode_queue")
        self._mock_queue = patcher.start()
        self.addCleanup(patcher.stop)

    def test_submit_creates_episode_and_enqueues(self):
        out = StringIO()
        call_command("submit_episode", "https://example.com/ep/1", stdout=out)

        self.assertEqual(Episode.objects.count(), 1)
        ep = Episode.objects.get(url="https://example.com/ep/1")
        self.assertIn(f"Submitted episode {ep.pk}", out.getvalue())
        self._mock_queue.enqueue.assert_called_once()

    def test_submit_existing_url_is_noop(self):
        Episode.objects.create(url="https://example.com/ep/dup")
        self._mock_queue.reset_mock()

        out = StringIO()
        call_command("submit_episode", "https://example.com/ep/dup", stdout=out)

        self.assertEqual(Episode.objects.count(), 1)
        self.assertIn("already exists", out.getvalue())
        # No new workflow enqueued for the existing URL.
        self._mock_queue.enqueue.assert_not_called()

    def test_invalid_url_rejected(self):
        with self.assertRaises(CommandError) as cm:
            call_command("submit_episode", "not-a-url")
        self.assertIn("Invalid URL", str(cm.exception))
        self.assertEqual(Episode.objects.count(), 0)
