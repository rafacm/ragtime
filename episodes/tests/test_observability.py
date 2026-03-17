"""Tests for the observability module (Langfuse integration)."""

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from episodes.observability import get_openai_client_class, is_enabled, observe_step


class IsEnabledTest(TestCase):
    """Tests for is_enabled()."""

    @override_settings(RAGTIME_LANGFUSE_ENABLED=False)
    def test_disabled_by_default(self):
        self.assertFalse(is_enabled())

    @override_settings(
        RAGTIME_LANGFUSE_ENABLED=True,
        RAGTIME_LANGFUSE_SECRET_KEY="sk-lf-secret",
        RAGTIME_LANGFUSE_PUBLIC_KEY="pk-lf-public",
        RAGTIME_LANGFUSE_HOST="http://localhost:3000",
    )
    def test_enabled_when_all_settings_present(self):
        self.assertTrue(is_enabled())

    @override_settings(
        RAGTIME_LANGFUSE_ENABLED=True,
        RAGTIME_LANGFUSE_SECRET_KEY="",
        RAGTIME_LANGFUSE_PUBLIC_KEY="pk-lf-public",
    )
    def test_disabled_when_secret_key_missing(self):
        self.assertFalse(is_enabled())

    @override_settings(
        RAGTIME_LANGFUSE_ENABLED=True,
        RAGTIME_LANGFUSE_SECRET_KEY="sk-lf-secret",
        RAGTIME_LANGFUSE_PUBLIC_KEY="",
    )
    def test_disabled_when_public_key_missing(self):
        self.assertFalse(is_enabled())

    @override_settings(
        RAGTIME_LANGFUSE_ENABLED=False,
        RAGTIME_LANGFUSE_SECRET_KEY="sk-lf-secret",
        RAGTIME_LANGFUSE_PUBLIC_KEY="pk-lf-public",
    )
    def test_disabled_when_enabled_false(self):
        self.assertFalse(is_enabled())

    @override_settings(
        RAGTIME_LANGFUSE_ENABLED=True,
        RAGTIME_LANGFUSE_SECRET_KEY="sk-lf-secret",
        RAGTIME_LANGFUSE_PUBLIC_KEY="pk-lf-public",
        RAGTIME_LANGFUSE_HOST="https://cloud.langfuse.com",
    )
    def test_sets_env_vars(self):
        env = {}
        with patch.dict(
            "os.environ", env, clear=True,
        ):
            is_enabled()
            import os
            self.assertEqual(os.environ.get("LANGFUSE_SECRET_KEY"), "sk-lf-secret")
            self.assertEqual(os.environ.get("LANGFUSE_PUBLIC_KEY"), "pk-lf-public")
            self.assertEqual(os.environ.get("LANGFUSE_HOST"), "https://cloud.langfuse.com")


class GetOpenaiClientClassTest(TestCase):
    """Tests for get_openai_client_class()."""

    @override_settings(RAGTIME_LANGFUSE_ENABLED=False)
    def test_returns_standard_openai_when_disabled(self):
        from openai import OpenAI

        result = get_openai_client_class()
        self.assertIs(result, OpenAI)

    @override_settings(
        RAGTIME_LANGFUSE_ENABLED=True,
        RAGTIME_LANGFUSE_SECRET_KEY="sk-lf-secret",
        RAGTIME_LANGFUSE_PUBLIC_KEY="pk-lf-public",
    )
    def test_falls_back_on_import_error(self):
        """When langfuse is not installed, falls back to openai.OpenAI."""
        from openai import OpenAI

        with patch.dict("sys.modules", {"langfuse": None, "langfuse.openai": None}):
            result = get_openai_client_class()
            self.assertIs(result, OpenAI)


class ObserveStepTest(TestCase):
    """Tests for observe_step() decorator."""

    @override_settings(RAGTIME_LANGFUSE_ENABLED=False)
    def test_noop_when_disabled(self):
        """When Langfuse is disabled, the decorator passes through."""
        called_with = {}

        @observe_step("test_step")
        def my_step(episode_id):
            called_with["episode_id"] = episode_id
            return "result"

        result = my_step(42)
        self.assertEqual(result, "result")
        self.assertEqual(called_with["episode_id"], 42)

    @override_settings(RAGTIME_LANGFUSE_ENABLED=False)
    def test_preserves_function_name(self):
        @observe_step("test_step")
        def my_step(episode_id):
            pass

        self.assertEqual(my_step.__name__, "my_step")

    @override_settings(
        RAGTIME_LANGFUSE_ENABLED=True,
        RAGTIME_LANGFUSE_SECRET_KEY="sk-lf-secret",
        RAGTIME_LANGFUSE_PUBLIC_KEY="pk-lf-public",
    )
    def test_falls_back_when_langfuse_not_installed(self):
        """When enabled but langfuse not installed, runs function normally."""
        called = []

        @observe_step("test_step")
        def my_step(episode_id):
            called.append(episode_id)
            return "ok"

        with patch.dict("sys.modules", {"langfuse": None}):
            result = my_step(99)

        self.assertEqual(result, "ok")
        self.assertEqual(called, [99])
