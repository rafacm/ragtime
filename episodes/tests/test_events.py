"""Tests for the ``classify_error`` helper.

The ``PipelineEvent`` / ``ProcessingRun`` / ``ProcessingStep`` models
were dropped along with the recovery layer; the persistence-side
tests that lived here are gone with them. ``classify_error`` is
still useful as a lightweight categorizer for log/telemetry strings,
so its tests stay.
"""

import json
import subprocess

from django.test import SimpleTestCase

from episodes.events import classify_error


class ClassifyErrorTests(SimpleTestCase):
    def test_http_status_error(self):
        import httpx

        response = httpx.Response(403)
        exc = httpx.HTTPStatusError(
            "Forbidden",
            request=httpx.Request("GET", "http://x"),
            response=response,
        )
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
