"""Tests for the telemetry module (OpenTelemetry integration)."""

from unittest.mock import patch

from django.test import TestCase, override_settings

from episodes.telemetry import (
    is_enabled,
    record_llm_input,
    trace_step,
)


class IsEnabledTest(TestCase):
    """Tests for is_enabled()."""

    @override_settings(RAGTIME_OTEL_ENABLED=False)
    def test_disabled_by_default(self):
        self.assertFalse(is_enabled())

    @override_settings(RAGTIME_OTEL_ENABLED=True)
    def test_disabled_during_test_runs(self):
        """is_enabled() returns False when sys.argv contains 'test'."""
        self.assertFalse(is_enabled())

    @override_settings(RAGTIME_OTEL_ENABLED=True)
    @patch("episodes.telemetry.sys")
    def test_enabled_when_setting_true(self, mock_sys):
        mock_sys.argv = ["manage.py", "runserver"]
        self.assertTrue(is_enabled())

    @override_settings(RAGTIME_OTEL_ENABLED=False)
    @patch("episodes.telemetry.sys")
    def test_disabled_when_setting_false(self, mock_sys):
        mock_sys.argv = ["manage.py", "runserver"]
        self.assertFalse(is_enabled())


class TraceStepTest(TestCase):
    """Tests for trace_step() decorator."""

    @override_settings(RAGTIME_OTEL_ENABLED=False)
    def test_noop_when_disabled(self):
        """When OTel is disabled, the decorator passes through."""
        called_with = {}

        @trace_step("test_step")
        def my_step(episode_id):
            called_with["episode_id"] = episode_id
            return "result"

        result = my_step(42)
        self.assertEqual(result, "result")
        self.assertEqual(called_with["episode_id"], 42)

    @override_settings(RAGTIME_OTEL_ENABLED=False)
    def test_preserves_function_name(self):
        @trace_step("test_step")
        def my_step(episode_id):
            pass

        self.assertEqual(my_step.__name__, "my_step")

    @override_settings(RAGTIME_OTEL_ENABLED=True)
    @patch("episodes.telemetry.sys")
    def test_falls_back_when_otel_not_installed(self, mock_sys):
        """When enabled but OTel not installed, runs function normally."""
        mock_sys.argv = ["manage.py", "runserver"]
        called = []

        @trace_step("test_step")
        def my_step(episode_id):
            called.append(episode_id)
            return "ok"

        # Even with OTel enabled, the function should still work
        # (get_tracer returns a no-op tracer if SDK isn't configured)
        result = my_step(99)
        self.assertIsNotNone(result)
        self.assertEqual(called, [99])


class RecordLlmInputTest(TestCase):
    """Tests for record_llm_input() calling conventions."""

    def test_chat_style_requires_exactly_two_positional_args(self):
        """Passing 1 or 3+ positional args raises TypeError."""
        with self.assertRaises(TypeError):
            record_llm_input("only_one")
        with self.assertRaises(TypeError):
            record_llm_input("one", "two", "three")

    def test_chat_style_rejects_unexpected_kwargs(self):
        """Chat-style only accepts response_schema as keyword arg."""
        with self.assertRaises(TypeError):
            record_llm_input("system", "user", bad_kwarg="nope")

    @override_settings(RAGTIME_OTEL_ENABLED=False)
    def test_noop_when_disabled(self):
        """No error when called with OTel disabled."""
        record_llm_input("system", "user")
        record_llm_input(audio_file="ep.mp3", model="whisper-1")
