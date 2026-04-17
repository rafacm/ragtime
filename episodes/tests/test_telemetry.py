"""Tests for the telemetry module (OpenTelemetry integration)."""

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from episodes.telemetry import (
    _configured_collectors,
    is_enabled,
    is_langfuse_enabled,
    record_llm_input,
    trace_step,
)


class ConfiguredCollectorsTest(TestCase):
    """Tests for _configured_collectors()."""

    @override_settings(RAGTIME_OTEL_COLLECTORS="")
    def test_empty_string_returns_empty_list(self):
        self.assertEqual(_configured_collectors(), [])

    @override_settings(RAGTIME_OTEL_COLLECTORS="console")
    def test_single_collector(self):
        self.assertEqual(_configured_collectors(), ["console"])

    @override_settings(RAGTIME_OTEL_COLLECTORS="console,jaeger")
    def test_multiple_collectors(self):
        self.assertEqual(_configured_collectors(), ["console", "jaeger"])

    @override_settings(RAGTIME_OTEL_COLLECTORS=" console , jaeger , langfuse ")
    def test_strips_whitespace(self):
        self.assertEqual(
            _configured_collectors(), ["console", "jaeger", "langfuse"]
        )

    @override_settings(RAGTIME_OTEL_COLLECTORS="Console,JAEGER")
    def test_lowercases_names(self):
        self.assertEqual(_configured_collectors(), ["console", "jaeger"])


class IsEnabledTest(TestCase):
    """Tests for is_enabled()."""

    @override_settings(RAGTIME_OTEL_COLLECTORS="")
    def test_disabled_when_no_collectors(self):
        self.assertFalse(is_enabled())

    @override_settings(RAGTIME_OTEL_COLLECTORS="console")
    def test_disabled_during_test_runs(self):
        """is_enabled() returns False when sys.argv contains 'test'."""
        self.assertFalse(is_enabled())

    @override_settings(RAGTIME_OTEL_COLLECTORS="console")
    @patch("episodes.telemetry.sys")
    def test_enabled_with_console_collector(self, mock_sys):
        mock_sys.argv = ["manage.py", "runserver"]
        self.assertTrue(is_enabled())

    @override_settings(RAGTIME_OTEL_COLLECTORS="jaeger")
    @patch("episodes.telemetry.sys")
    def test_enabled_with_jaeger_collector(self, mock_sys):
        mock_sys.argv = ["manage.py", "runserver"]
        self.assertTrue(is_enabled())

    @override_settings(RAGTIME_OTEL_COLLECTORS="console,jaeger,langfuse")
    @patch("episodes.telemetry.sys")
    def test_enabled_with_multiple_collectors(self, mock_sys):
        mock_sys.argv = ["manage.py", "runserver"]
        self.assertTrue(is_enabled())


class IsLangfuseEnabledTest(TestCase):
    """Tests for is_langfuse_enabled()."""

    @override_settings(RAGTIME_OTEL_COLLECTORS="console")
    @patch("episodes.telemetry.sys")
    def test_false_when_langfuse_not_in_collectors(self, mock_sys):
        mock_sys.argv = ["manage.py", "runserver"]
        self.assertFalse(is_langfuse_enabled())

    @override_settings(RAGTIME_OTEL_COLLECTORS="langfuse")
    @patch("episodes.telemetry.sys")
    def test_true_when_langfuse_in_collectors(self, mock_sys):
        mock_sys.argv = ["manage.py", "runserver"]
        self.assertTrue(is_langfuse_enabled())

    @override_settings(RAGTIME_OTEL_COLLECTORS="console,langfuse")
    @patch("episodes.telemetry.sys")
    def test_true_when_langfuse_among_multiple(self, mock_sys):
        mock_sys.argv = ["manage.py", "runserver"]
        self.assertTrue(is_langfuse_enabled())

    @override_settings(RAGTIME_OTEL_COLLECTORS="")
    def test_false_when_disabled(self):
        self.assertFalse(is_langfuse_enabled())


class TraceStepTest(TestCase):
    """Tests for trace_step() decorator."""

    @override_settings(RAGTIME_OTEL_COLLECTORS="")
    def test_noop_when_disabled(self):
        """When no collectors, the decorator passes through."""
        called_with = {}

        @trace_step("test_step")
        def my_step(episode_id):
            called_with["episode_id"] = episode_id
            return "result"

        result = my_step(42)
        self.assertEqual(result, "result")
        self.assertEqual(called_with["episode_id"], 42)

    @override_settings(RAGTIME_OTEL_COLLECTORS="")
    def test_preserves_function_name(self):
        @trace_step("test_step")
        def my_step(episode_id):
            pass

        self.assertEqual(my_step.__name__, "my_step")


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

    @override_settings(RAGTIME_OTEL_COLLECTORS="")
    def test_noop_when_disabled(self):
        """No error when disabled — just returns silently."""
        record_llm_input("system", "user")
        record_llm_input(audio_file="ep.mp3", model="whisper-1")

    @override_settings(RAGTIME_OTEL_COLLECTORS="console")
    @patch("episodes.telemetry.sys")
    def test_chat_style_adds_span_event(self, mock_sys):
        """Chat-style records input as a span event."""
        mock_sys.argv = ["manage.py", "runserver"]
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        with patch("opentelemetry.trace.get_current_span", return_value=mock_span):
            record_llm_input("You are a bot", "Hello")

        mock_span.add_event.assert_called_once()
        call_args = mock_span.add_event.call_args
        self.assertEqual(call_args[0][0], "llm.input")
        attrs = call_args[1]["attributes"]
        self.assertEqual(attrs["llm.input.system"], "You are a bot")
        self.assertEqual(attrs["llm.input.user"], "Hello")

    @override_settings(RAGTIME_OTEL_COLLECTORS="console")
    @patch("episodes.telemetry.sys")
    def test_dict_style_adds_span_event(self, mock_sys):
        """Dict-style records input as a span event."""
        mock_sys.argv = ["manage.py", "runserver"]
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        with patch("opentelemetry.trace.get_current_span", return_value=mock_span):
            record_llm_input(audio_file="ep.mp3", model="whisper-1")

        mock_span.add_event.assert_called_once()
        call_args = mock_span.add_event.call_args
        self.assertEqual(call_args[0][0], "llm.input")
        attrs = call_args[1]["attributes"]
        self.assertEqual(attrs["llm.input.audio_file"], "ep.mp3")
        self.assertEqual(attrs["llm.input.model"], "whisper-1")
