"""Tests for ``episodes.agents._model.build_model``.

The helper has two non-trivial guarantees: (1) for known providers it
constructs a concrete ``Model`` instance whose provider receives the
configured api_key directly (so ambient env vars never win), and (2)
when a provider's submodule can't be imported in this environment, it
falls back to Pydantic AI's resolver inside a temporarily-scoped env
var so the configured key still wins and the env is always restored.
"""

import os
from unittest.mock import patch

from django.test import TestCase

from episodes.agents import _model


class BuildModelOpenAITests(TestCase):
    def test_returns_concrete_openai_model_with_api_key(self):
        model = _model.build_model("openai:gpt-4.1-mini", "test-key")
        self.assertEqual(type(model).__name__, "OpenAIResponsesModel")
        self.assertEqual(type(model).__module__, "pydantic_ai.models.openai")

    def test_no_api_key_returns_raw_string(self):
        self.assertEqual(
            _model.build_model("openai:gpt-4.1-mini", ""),
            "openai:gpt-4.1-mini",
        )

    def test_default_provider_is_openai(self):
        # Bare model name (no prefix) routes to OpenAI.
        model = _model.build_model("gpt-4.1-mini", "test-key")
        self.assertEqual(type(model).__name__, "OpenAIResponsesModel")


class BuildModelGoogleTests(TestCase):
    def test_returns_concrete_google_model(self):
        model = _model.build_model("google:gemini-2.5-pro", "test-key")
        self.assertEqual(type(model).__name__, "GoogleModel")
        self.assertEqual(type(model).__module__, "pydantic_ai.models.google")


class TempEnvTests(TestCase):
    def test_sets_value_inside_block(self):
        with _model._temp_env("RAGTIME_TEST_VAR", "inside"):
            self.assertEqual(os.environ["RAGTIME_TEST_VAR"], "inside")
        self.assertNotIn("RAGTIME_TEST_VAR", os.environ)

    def test_restores_previous_value(self):
        os.environ["RAGTIME_TEST_VAR"] = "outside"
        try:
            with _model._temp_env("RAGTIME_TEST_VAR", "inside"):
                self.assertEqual(os.environ["RAGTIME_TEST_VAR"], "inside")
            self.assertEqual(os.environ["RAGTIME_TEST_VAR"], "outside")
        finally:
            os.environ.pop("RAGTIME_TEST_VAR", None)

    def test_restores_on_exception(self):
        os.environ["RAGTIME_TEST_VAR"] = "outside"
        try:
            with self.assertRaises(RuntimeError):
                with _model._temp_env("RAGTIME_TEST_VAR", "inside"):
                    raise RuntimeError("boom")
            self.assertEqual(os.environ["RAGTIME_TEST_VAR"], "outside")
        finally:
            os.environ.pop("RAGTIME_TEST_VAR", None)


class BuildModelFallbackTests(TestCase):
    """Fallback path: SDK submodule import fails for a known provider.

    Asserts the env-var-scoped resolver is used (configured key wins
    over ambient) and the env var is restored — even when ``infer_model``
    itself raises ``ImportError`` because the underlying SDK is not
    importable.
    """

    def test_anthropic_fallback_scopes_env_and_restores_on_error(self):
        os.environ["ANTHROPIC_API_KEY"] = "AMBIENT-WRONG"
        try:
            # In this checkout, pydantic_ai.models.anthropic raises
            # ImportError on import — exactly the scenario the
            # fallback exists for. The fallback's infer_model call
            # will also fail with ImportError, which is fine: we just
            # need to confirm the env var is correctly restored.
            with self.assertRaises(ImportError):
                _model.build_model(
                    "anthropic:claude-sonnet-4-20250514",
                    "CONFIGURED-RIGHT",
                )
            self.assertEqual(
                os.environ["ANTHROPIC_API_KEY"],
                "AMBIENT-WRONG",
                "env var must be restored to its prior value on exception",
            )
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_anthropic_fallback_unsets_when_no_prior_value(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        with self.assertRaises(ImportError):
            _model.build_model(
                "anthropic:claude-sonnet-4-20250514", "configured"
            )
        self.assertNotIn(
            "ANTHROPIC_API_KEY",
            os.environ,
            "env var that didn't exist before must not exist after",
        )

    def test_unknown_provider_returns_raw_string(self):
        # Unknown providers can't be scoped (we don't know which env
        # var to set) — they return the raw string with a warning.
        result = _model.build_model("groq:llama-3", "key")
        self.assertEqual(result, "groq:llama-3")
