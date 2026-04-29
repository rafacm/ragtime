"""Tests for the configure management command and its helpers."""

import os
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from core.management.commands._configure_helpers import (
    mask_secret,
    prompt_value,
    read_env,
    write_env,
)


class ReadEnvTest(TestCase):
    """Tests for read_env()."""

    def test_parse_key_value(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("FOO=bar\nBAZ=qux\n")
            f.flush()
            values, lines = read_env(f.name)
        os.unlink(f.name)
        self.assertEqual(values, {"FOO": "bar", "BAZ": "qux"})
        self.assertEqual(len(lines), 2)

    def test_preserves_comments(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# This is a comment\nFOO=bar\n")
            f.flush()
            values, lines = read_env(f.name)
        os.unlink(f.name)
        self.assertEqual(values, {"FOO": "bar"})
        self.assertEqual(len(lines), 2)
        self.assertIn("# This is a comment\n", lines)

    def test_strips_quotes(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write('FOO="bar"\nBAZ=\'qux\'\n')
            f.flush()
            values, _ = read_env(f.name)
        os.unlink(f.name)
        self.assertEqual(values, {"FOO": "bar", "BAZ": "qux"})

    def test_handles_value_with_equals(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("FOO=bar=baz\n")
            f.flush()
            values, _ = read_env(f.name)
        os.unlink(f.name)
        self.assertEqual(values, {"FOO": "bar=baz"})

    def test_missing_file(self):
        values, lines = read_env("/nonexistent/.env")
        self.assertEqual(values, {})
        self.assertEqual(lines, [])

    def test_blank_lines_preserved(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("FOO=bar\n\nBAZ=qux\n")
            f.flush()
            values, lines = read_env(f.name)
        os.unlink(f.name)
        self.assertEqual(values, {"FOO": "bar", "BAZ": "qux"})
        self.assertEqual(len(lines), 3)


class WriteEnvTest(TestCase):
    """Tests for write_env()."""

    def test_updates_existing_keys(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False
        ) as f:
            f.write("FOO=old\nBAR=keep\n")
            path = f.name
        write_env(path, {"FOO": "new", "BAR": "keep"}, ["FOO=old\n", "BAR=keep\n"])
        values, _ = read_env(path)
        os.unlink(path)
        self.assertEqual(values["FOO"], "new")
        self.assertEqual(values["BAR"], "keep")

    def test_preserves_comments(self):
        original = ["# Comment\n", "FOO=old\n"]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False
        ) as f:
            path = f.name
        write_env(path, {"FOO": "new"}, original)
        with open(path) as f:
            content = f.read()
        os.unlink(path)
        self.assertIn("# Comment", content)
        self.assertIn("FOO=new", content)

    def test_appends_new_keys(self):
        original = ["FOO=bar\n"]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False
        ) as f:
            path = f.name
        write_env(path, {"FOO": "bar", "NEW": "value"}, original)
        values, _ = read_env(path)
        os.unlink(path)
        self.assertEqual(values["FOO"], "bar")
        self.assertEqual(values["NEW"], "value")

    def test_preserves_non_ragtime_lines(self):
        original = ["DEBUG=true\n", "RAGTIME_SUMMARIZATION_PROVIDER=openai\n"]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False
        ) as f:
            path = f.name
        write_env(
            path,
            {"DEBUG": "true", "RAGTIME_SUMMARIZATION_PROVIDER": "anthropic"},
            original,
        )
        values, _ = read_env(path)
        os.unlink(path)
        self.assertEqual(values["DEBUG"], "true")
        self.assertEqual(values["RAGTIME_SUMMARIZATION_PROVIDER"], "anthropic")


class MaskSecretTest(TestCase):
    """Tests for mask_secret()."""

    def test_empty_string(self):
        self.assertEqual(mask_secret(""), "")

    def test_short_string(self):
        self.assertEqual(mask_secret("abc"), "***")

    def test_normal_string(self):
        self.assertEqual(mask_secret("sk-1234567xQ2"), "***7xQ2")

    def test_exactly_four_chars(self):
        self.assertEqual(mask_secret("abcd"), "***abcd")


class PromptValueTest(TestCase):
    """Tests for prompt_value()."""

    @patch("builtins.input", return_value="new_value")
    def test_returns_user_input(self, mock_input):
        result = prompt_value("Provider", "openai", False)
        self.assertEqual(result, "new_value")

    @patch("builtins.input", return_value="")
    def test_returns_current_on_empty_input(self, mock_input):
        result = prompt_value("Provider", "openai", False)
        self.assertEqual(result, "openai")

    @patch("core.management.commands._configure_helpers.getpass.getpass", return_value="secret")
    def test_uses_getpass_for_secrets(self, mock_getpass):
        result = prompt_value("API key", "", True)
        self.assertEqual(result, "secret")
        mock_getpass.assert_called_once()

    @patch("core.management.commands._configure_helpers.getpass.getpass", return_value="")
    def test_secret_keeps_current_on_empty(self, mock_getpass):
        result = prompt_value("API key", "existing-key", True)
        self.assertEqual(result, "existing-key")


class ConfigureShowTest(TestCase):
    """Tests for `manage.py configure --show`."""

    def test_show_with_existing_values(self):
        env_content = (
            "RAGTIME_FETCH_DETAILS_API_KEY=sk-test1234567890\n"
            "RAGTIME_FETCH_DETAILS_MODEL=openai:gpt-4.1-mini\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False, dir="."
        ) as f:
            f.write(env_content)
            env_path = Path(f.name)

        try:
            out = StringIO()
            with override_settings(BASE_DIR=env_path.parent):
                # Patch read_env to point to our temp file
                with patch(
                    "core.management.commands.configure.read_env"
                ) as mock_read:
                    mock_read.return_value = (
                        {
                            "RAGTIME_FETCH_DETAILS_API_KEY": "sk-test1234567890",
                            "RAGTIME_FETCH_DETAILS_MODEL": "openai:gpt-4.1-mini",
                        },
                        [],
                    )
                    call_command("configure", "--show", stdout=out)

            output = out.getvalue()
            # API key should be masked
            self.assertIn("***7890", output)
            self.assertNotIn("sk-test1234567890", output)
            self.assertIn("RAGTIME_FETCH_DETAILS_MODEL=openai:gpt-4.1-mini", output)
        finally:
            env_path.unlink(missing_ok=True)

    def test_show_with_no_values(self):
        out = StringIO()
        with patch("core.management.commands.configure.read_env") as mock_read:
            mock_read.return_value = ({}, [])
            call_command("configure", "--show", stdout=out)

        self.assertIn("No RAGTIME_* variables configured", out.getvalue())


class ConfigureWizardTest(TestCase):
    """Tests for the interactive wizard flow."""

    @patch("core.management.commands._configure_helpers.getpass.getpass")
    @patch("builtins.input")
    def test_shared_mode_anthropic_proposes_anthropic_default_suffix(
        self, mock_input, mock_getpass
    ):
        """When the shared provider is anthropic, the Convention B model
        default must be ``anthropic:<anthropic-default>``, not a stale
        ``anthropic:gpt-4.1-mini`` left over from the openai default."""
        mock_getpass.side_effect = [
            "",               # DB password (keep default)
            "sk-anthropic",   # Shared LLM API key
            "",               # Transcription API key (keep default)
            "",               # Embedding API key
            "",               # Qdrant API key
            "",               # Scott API key
            "",               # MusicBrainz DB password
            "",               # Download Agent API key
            "",               # FYYD API key
            "",               # PodcastIndex API key
            "",               # PodcastIndex API secret
            "",               # Langfuse secret key
            "",               # Langfuse public key
        ]
        mock_input.side_effect = [
            "", "", "", "",   # DB
            "Y",              # Share provider/key? Yes
            "anthropic",      # Shared provider
            # User presses Enter to accept the proposed default for
            # Fetch Details — the wizard must have rebuilt it with an
            # Anthropic-appropriate suffix, not left a stale openai one.
            "",
            "claude-sonnet-4-20250514",  # Summarization model
            "claude-sonnet-4-20250514",  # Extraction
            "claude-sonnet-4-20250514",  # Resolution
            "claude-sonnet-4-20250514",  # Translation
            "openai", "whisper-1",       # Transcription
            "", "",                       # Embedding
            "", "", "", "",               # Qdrant
            "", "", "", "",               # Scott
            "", "", "", "", "",           # MusicBrainz
            "",                            # Pipeline
            "", "", "", "", "",            # Wikidata
            "", "",                        # Download Agent (model, timeout)
            "",                            # Podcast Aggregators (PODCAST_AGGREGATORS list)
            "", "", "",                    # OTel
            "",                             # Langfuse host
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False
        ) as f:
            env_path = Path(f.name)
        try:
            out = StringIO()
            with patch(
                "core.management.commands.configure.read_env"
            ) as mock_read:
                mock_read.return_value = ({}, [])
                with patch(
                    "core.management.commands.configure.write_env"
                ) as mock_write:
                    with override_settings(BASE_DIR=env_path.parent):
                        call_command("configure", stdout=out)
                values = mock_write.call_args[0][1]
                # Critical assertion — the proposed default the user
                # accepted must be a valid Anthropic model string.
                self.assertEqual(
                    values["RAGTIME_FETCH_DETAILS_MODEL"],
                    "anthropic:claude-sonnet-4-20250514",
                )
                # No _PROVIDER for Convention B
                self.assertNotIn("RAGTIME_FETCH_DETAILS_PROVIDER", values)
        finally:
            env_path.unlink(missing_ok=True)

    @patch("core.management.commands._configure_helpers.getpass.getpass")
    @patch("builtins.input")
    def test_shared_mode_wizard(self, mock_input, mock_getpass):
        """Test wizard with shared LLM provider/key."""
        mock_getpass.side_effect = [
            "",               # DB password (keep default)
            "sk-newkey123",   # Shared LLM API key
            "sk-newkey123",   # Transcription API key
            "",               # Embedding API key (reuse shared LLM key)
            "",               # Qdrant API key (keep default)
            "",               # Scott API key (keep default)
            "",               # MusicBrainz DB password (keep default)
            "",               # Download Agent API key (keep default)
            "",               # FYYD API key
            "",               # PodcastIndex API key
            "",               # PodcastIndex API secret
            "",               # Langfuse secret key (keep default)
            "",               # Langfuse public key (keep default)
        ]
        mock_input.side_effect = [
            "",               # DB name (keep default)
            "",               # DB user (keep default)
            "",               # DB host (keep default)
            "",               # DB port (keep default)
            "Y",              # Share provider/key? Yes
            "openai",         # Provider
            "openai:gpt-4.1-mini",  # Fetch Details model (Convention B)
            "gpt-4.1-mini",  # Summarization model
            "gpt-4.1-mini",  # Extraction model
            "gpt-4.1-mini",  # Resolution model
            "gpt-4.1-mini",  # Translation model
            "openai",         # Transcription provider
            "whisper-1",      # Transcription model
            "",               # Embedding provider (keep default)
            "",               # Embedding model (keep default)
            "",               # Qdrant host (keep default)
            "",               # Qdrant port (keep default)
            "",               # Qdrant collection (keep default)
            "",               # Qdrant https (keep default)
            "",               # Scott provider (keep default)
            "",               # Scott model (keep default)
            "",               # Scott top_k (keep default)
            "",               # Scott score threshold (keep default)
            "",               # MusicBrainz DB host
            "",               # MusicBrainz DB port
            "",               # MusicBrainz DB name
            "",               # MusicBrainz DB user
            "",               # MusicBrainz schema
            "",               # Pipeline EPISODE_CONCURRENCY
            "",               # Wikidata user agent (keep default)
            "",               # Wikidata cache backend (keep default)
            "",               # Wikidata cache TTL (keep default)
            "",               # Wikidata debounce ms (keep default)
            "",               # Wikidata min chars (keep default)
            "",               # Download Agent model (keep default)
            "",               # Download Agent timeout (keep default)
            "",               # Podcast Aggregators (RAGTIME_PODCAST_AGGREGATORS list)
            "",               # OTel collectors (keep default)
            "",               # OTel service name (keep default)
            "",               # OTel Jaeger endpoint (keep default)
            "",               # Langfuse host (keep default)
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False
        ) as f:
            env_path = Path(f.name)

        try:
            out = StringIO()
            with patch(
                "core.management.commands.configure.read_env"
            ) as mock_read:
                mock_read.return_value = ({}, [])
                with patch(
                    "core.management.commands.configure.write_env"
                ) as mock_write:
                    with override_settings(BASE_DIR=env_path.parent):
                        call_command("configure", stdout=out)

                    # Verify write_env was called with expected values
                    call_args = mock_write.call_args
                    values = call_args[0][1]

                    # Fetch Details follows Convention B — no _PROVIDER var
                    self.assertNotIn("RAGTIME_FETCH_DETAILS_PROVIDER", values)
                    self.assertEqual(
                        values["RAGTIME_FETCH_DETAILS_MODEL"],
                        "openai:gpt-4.1-mini",
                    )
                    self.assertEqual(
                        values["RAGTIME_FETCH_DETAILS_API_KEY"], "sk-newkey123"
                    )
                    # Other LLM subsystems still keep the old PROVIDER convention
                    self.assertEqual(
                        values["RAGTIME_SUMMARIZATION_PROVIDER"], "openai"
                    )
                    self.assertEqual(
                        values["RAGTIME_SUMMARIZATION_API_KEY"], "sk-newkey123"
                    )
                    self.assertEqual(
                        values["RAGTIME_EXTRACTION_API_KEY"], "sk-newkey123"
                    )
                    self.assertEqual(
                        values["RAGTIME_RESOLUTION_API_KEY"], "sk-newkey123"
                    )
                    self.assertEqual(
                        values["RAGTIME_TRANSLATION_API_KEY"], "sk-newkey123"
                    )
                    self.assertEqual(
                        values["RAGTIME_TRANSCRIPTION_PROVIDER"], "openai"
                    )

            self.assertIn("Configuration written to", out.getvalue())
        finally:
            env_path.unlink(missing_ok=True)

    @patch(
        "core.management.commands._configure_helpers.getpass.getpass",
        return_value="",
    )
    @patch("builtins.input")
    def test_keyboard_interrupt_writes_nothing(self, mock_input, mock_getpass):
        """Test that Ctrl+C cancels without writing."""
        mock_input.side_effect = KeyboardInterrupt()

        out = StringIO()
        with patch("core.management.commands.configure.read_env") as mock_read:
            mock_read.return_value = ({}, [])
            with patch(
                "core.management.commands.configure.write_env"
            ) as mock_write:
                call_command("configure", stdout=out)
                mock_write.assert_not_called()

        self.assertIn("cancelled", out.getvalue())

    @patch("core.management.commands._configure_helpers.getpass.getpass")
    @patch("builtins.input")
    def test_rerun_preserves_non_ragtime_lines(self, mock_input, mock_getpass):
        """Test that re-running preserves non-RAGTIME lines."""
        mock_getpass.side_effect = [
            "",               # DB password (keep default)
            "sk-newkey123",   # Shared LLM API key
            "sk-newkey123",   # Transcription API key
            "",               # Embedding API key (reuse shared LLM key)
            "",               # Qdrant API key (keep default)
            "",               # Scott API key (keep default)
            "",               # MusicBrainz DB password (keep default)
            "",               # Download Agent API key (keep default)
            "",               # FYYD API key
            "",               # PodcastIndex API key
            "",               # PodcastIndex API secret
            "",               # Langfuse secret key (keep default)
            "",               # Langfuse public key (keep default)
        ]
        mock_input.side_effect = [
            "",               # DB name (keep default)
            "",               # DB user (keep default)
            "",               # DB host (keep default)
            "",               # DB port (keep default)
            "Y",              # Share provider/key? Yes
            "openai",         # Provider
            "openai:gpt-4.1-mini",  # Fetch Details model (Convention B)
            "gpt-4.1-mini",  # Summarization model
            "gpt-4.1-mini",  # Extraction model
            "gpt-4.1-mini",  # Resolution model
            "gpt-4.1-mini",  # Translation model
            "openai",         # Transcription provider
            "whisper-1",      # Transcription model
            "",               # Embedding provider (keep default)
            "",               # Embedding model (keep default)
            "",               # Qdrant host (keep default)
            "",               # Qdrant port (keep default)
            "",               # Qdrant collection (keep default)
            "",               # Qdrant https (keep default)
            "",               # Scott provider (keep default)
            "",               # Scott model (keep default)
            "",               # Scott top_k (keep default)
            "",               # Scott score threshold (keep default)
            "",               # MusicBrainz DB host
            "",               # MusicBrainz DB port
            "",               # MusicBrainz DB name
            "",               # MusicBrainz DB user
            "",               # MusicBrainz schema
            "",               # Pipeline EPISODE_CONCURRENCY
            "",               # Wikidata user agent (keep default)
            "",               # Wikidata cache backend (keep default)
            "",               # Wikidata cache TTL (keep default)
            "",               # Wikidata debounce ms (keep default)
            "",               # Wikidata min chars (keep default)
            "",               # Download Agent model (keep default)
            "",               # Download Agent timeout (keep default)
            "",               # Podcast Aggregators (RAGTIME_PODCAST_AGGREGATORS list)
            "",               # OTel collectors (keep default)
            "",               # OTel service name (keep default)
            "",               # OTel Jaeger endpoint (keep default)
            "",               # Langfuse host (keep default)
        ]

        original_lines = ["# My config\n", "DEBUG=true\n", "RAGTIME_SUMMARIZATION_PROVIDER=openai\n"]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False
        ) as f:
            env_path = Path(f.name)

        try:
            out = StringIO()
            with patch(
                "core.management.commands.configure.read_env"
            ) as mock_read:
                mock_read.return_value = (
                    {
                        "DEBUG": "true",
                        "RAGTIME_SUMMARIZATION_PROVIDER": "openai",
                    },
                    original_lines,
                )
                with patch(
                    "core.management.commands.configure.write_env"
                ) as mock_write:
                    with override_settings(BASE_DIR=env_path.parent):
                        call_command("configure", stdout=out)

                    call_args = mock_write.call_args
                    written_lines = call_args[0][2]
                    self.assertIn("# My config\n", written_lines)
                    self.assertIn("DEBUG=true\n", written_lines)
        finally:
            env_path.unlink(missing_ok=True)

    @patch("core.management.commands._configure_helpers.getpass.getpass")
    @patch("builtins.input")
    def test_warns_when_embedding_model_changes(self, mock_input, mock_getpass):
        """Changing RAGTIME_EMBEDDING_MODEL prints a Qdrant-reset warning."""
        mock_getpass.side_effect = [
            "",               # DB password (keep default)
            "sk-newkey123",   # Shared LLM API key
            "sk-newkey123",   # Transcription API key
            "",               # Embedding API key (reuse shared LLM key)
            "",               # Qdrant API key (keep default)
            "",               # Scott API key (keep default)
            "",               # MusicBrainz DB password (keep default)
            "",               # Download Agent API key (keep default)
            "",               # FYYD API key
            "",               # PodcastIndex API key
            "",               # PodcastIndex API secret
            "",               # Langfuse secret key (keep default)
            "",               # Langfuse public key (keep default)
        ]
        mock_input.side_effect = [
            "",               # DB name (keep default)
            "",               # DB user (keep default)
            "",               # DB host (keep default)
            "",               # DB port (keep default)
            "Y",              # Share provider/key? Yes
            "openai",         # Provider
            "openai:gpt-4.1-mini",  # Fetch Details (Convention B)
            "gpt-4.1-mini",
            "gpt-4.1-mini",
            "gpt-4.1-mini",
            "gpt-4.1-mini",
            "openai",         # Transcription provider
            "whisper-1",
            "",               # Embedding provider (keep default)
            "text-embedding-3-large",  # Embedding model (CHANGED)
            "",               # Qdrant host
            "",               # Qdrant port
            "",               # Qdrant collection
            "",               # Qdrant https
            "", "", "", "",     # Scott (4 non-secret fields)
            "", "", "", "", "", # MusicBrainz DB host/port/name/user + schema
            "",                 # Pipeline EPISODE_CONCURRENCY
            "", "", "", "", "",  # Wikidata (5 fields)
            "", "",             # Download Agent (model, timeout)
            "",                 # Podcast Aggregators (RAGTIME_PODCAST_AGGREGATORS list)
            "", "", "",         # OTel (3 fields)
            "",                 # Langfuse host
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False
        ) as f:
            env_path = Path(f.name)

        try:
            out = StringIO()
            with patch(
                "core.management.commands.configure.read_env"
            ) as mock_read:
                mock_read.return_value = (
                    {"RAGTIME_EMBEDDING_MODEL": "text-embedding-3-small"},
                    [],
                )
                with patch("core.management.commands.configure.write_env"):
                    with override_settings(BASE_DIR=env_path.parent):
                        call_command("configure", stdout=out)

            output = out.getvalue()
            self.assertIn("RAGTIME_EMBEDDING_MODEL changed", output)
            self.assertIn("text-embedding-3-small", output)
            self.assertIn("text-embedding-3-large", output)
            self.assertIn("dbreset", output)
        finally:
            env_path.unlink(missing_ok=True)
