"""Tests for ``manage.py submit_episodes``."""

import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from episodes.models import Episode


class SubmitEpisodesTests(TestCase):
    def setUp(self):
        # Patch the pipeline queue so creating Episodes doesn't try to talk
        # to a live DBOS runtime.
        patcher = patch("episodes.workflows.episode_queue")
        self._mock_queue = patcher.start()
        self.addCleanup(patcher.stop)

    def test_submit_single_url(self):
        out = StringIO()
        call_command(
            "submit_episodes", "https://example.com/ep/1", stdout=out
        )
        self.assertEqual(Episode.objects.count(), 1)
        self.assertEqual(
            Episode.objects.first().url, "https://example.com/ep/1"
        )
        self.assertIn("Submitted 1", out.getvalue())
        # Signal handler enqueued exactly one workflow.
        self.assertEqual(self._mock_queue.enqueue.call_count, 1)

    def test_submit_multiple_urls(self):
        out = StringIO()
        call_command(
            "submit_episodes",
            "https://example.com/ep/a",
            "https://example.com/ep/b",
            "https://example.com/ep/c",
            stdout=out,
        )
        self.assertEqual(Episode.objects.count(), 3)
        self.assertEqual(self._mock_queue.enqueue.call_count, 3)
        self.assertIn("Submitted 3", out.getvalue())

    def test_skips_duplicates(self):
        Episode.objects.create(url="https://example.com/ep/dup")

        out = StringIO()
        call_command(
            "submit_episodes",
            "https://example.com/ep/dup",
            "https://example.com/ep/new",
            stdout=out,
        )
        self.assertEqual(Episode.objects.count(), 2)
        self.assertIn("Submitted 1", out.getvalue())
        self.assertIn("skipped 1", out.getvalue())
        # Only the new URL was enqueued (plus the one from the setUp create).
        # setUp create fired the signal once, the new URL fires it once more.
        self.assertEqual(self._mock_queue.enqueue.call_count, 2)

    def test_dedups_within_input(self):
        out = StringIO()
        call_command(
            "submit_episodes",
            "https://example.com/ep/x",
            "https://example.com/ep/x",
            "https://example.com/ep/y",
            stdout=out,
        )
        self.assertEqual(Episode.objects.count(), 2)
        self.assertIn("Submitted 2", out.getvalue())

    def test_file_input(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(
                "# Comment line, ignored\n"
                "https://example.com/ep/from-file-1\n"
                "\n"  # blank line, ignored
                "  https://example.com/ep/from-file-2  \n"  # whitespace stripped
                "# another comment\n"
            )
            path = Path(f.name)

        try:
            out = StringIO()
            call_command("submit_episodes", "--file", str(path), stdout=out)
            self.assertEqual(Episode.objects.count(), 2)
            urls = set(Episode.objects.values_list("url", flat=True))
            self.assertEqual(
                urls,
                {
                    "https://example.com/ep/from-file-1",
                    "https://example.com/ep/from-file-2",
                },
            )
        finally:
            path.unlink(missing_ok=True)

    def test_stdin_input(self):
        out = StringIO()
        with patch(
            "sys.stdin",
            StringIO(
                "https://example.com/ep/stdin-1\n"
                "https://example.com/ep/stdin-2\n"
            ),
        ):
            call_command("submit_episodes", "--file", "-", stdout=out)
        self.assertEqual(Episode.objects.count(), 2)

    def test_dry_run_creates_nothing(self):
        out = StringIO()
        call_command(
            "submit_episodes",
            "https://example.com/ep/dry",
            "--dry-run",
            stdout=out,
        )
        self.assertEqual(Episode.objects.count(), 0)
        self.assertEqual(self._mock_queue.enqueue.call_count, 0)
        self.assertIn("dry-run", out.getvalue())
        self.assertIn("Would submit 1", out.getvalue())

    def test_dry_run_marks_duplicates(self):
        Episode.objects.create(url="https://example.com/ep/dup")
        out = StringIO()
        call_command(
            "submit_episodes",
            "https://example.com/ep/dup",
            "https://example.com/ep/new",
            "--dry-run",
            stdout=out,
        )
        self.assertEqual(Episode.objects.count(), 1)  # dry-run added nothing
        self.assertIn("Would submit 1", out.getvalue())
        self.assertIn("skip 1", out.getvalue())

    def test_no_urls_raises(self):
        with self.assertRaises(CommandError) as cm:
            call_command("submit_episodes")
        self.assertIn("No URLs supplied", str(cm.exception))

    def test_args_and_file_mutually_exclusive(self):
        with self.assertRaises(CommandError) as cm:
            call_command(
                "submit_episodes",
                "https://example.com/ep/1",
                "--file",
                "urls.txt",
            )
        self.assertIn("not both", str(cm.exception))

    def test_invalid_url_rejected(self):
        with self.assertRaises(CommandError) as cm:
            call_command("submit_episodes", "not-a-url")
        self.assertIn("Invalid URL", str(cm.exception))

    def test_missing_file_raises(self):
        with self.assertRaises(CommandError) as cm:
            call_command("submit_episodes", "--file", "/no/such/file.txt")
        self.assertIn("Could not read", str(cm.exception))
