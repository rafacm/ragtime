"""Tests for Langfuse tool-definition logging in the recovery agent."""

import unittest
from unittest.mock import MagicMock, patch

try:
    from pydantic_ai import Agent

    from episodes.agents.agent import _get_tool_definitions, _log_tool_definitions

    _has_pydantic_ai = True
except ImportError:
    _has_pydantic_ai = False


@unittest.skipUnless(_has_pydantic_ai, "pydantic-ai not installed")
class GetToolDefinitionsTests(unittest.TestCase):
    """Tests for _get_tool_definitions()."""

    def test_extracts_tool_names_and_schemas(self):
        """Returns a list of dicts with name, description, and parameters."""
        agent = Agent("test", deps_type=None)

        @agent.tool_plain
        def greet(name: str) -> str:
            """Say hello."""
            return f"Hello, {name}"

        defs = _get_tool_definitions(agent)

        self.assertEqual(len(defs), 1)
        self.assertEqual(defs[0]["name"], "greet")
        self.assertEqual(defs[0]["description"], "Say hello.")
        self.assertIn("properties", defs[0]["parameters"])
        self.assertIn("name", defs[0]["parameters"]["properties"])

    def test_returns_empty_list_on_error(self):
        """Gracefully returns [] when the agent has no _function_toolset."""
        fake_agent = MagicMock(spec=[])  # no attributes at all
        self.assertEqual(_get_tool_definitions(fake_agent), [])

    def test_handles_multiple_tools(self):
        """Extracts definitions for all registered tools."""
        agent = Agent("test", deps_type=None)

        @agent.tool_plain
        def tool_a(x: int) -> str:
            """First tool."""
            return str(x)

        @agent.tool_plain
        def tool_b(y: str) -> str:
            """Second tool."""
            return y

        defs = _get_tool_definitions(agent)
        names = {d["name"] for d in defs}
        self.assertEqual(names, {"tool_a", "tool_b"})


@unittest.skipUnless(_has_pydantic_ai, "pydantic-ai not installed")
class LogToolDefinitionsTests(unittest.TestCase):
    """Tests for _log_tool_definitions()."""

    @patch("episodes.agents.agent.langfuse", create=True)
    def test_creates_langfuse_event(self, mock_langfuse_module):
        """Logs tool definitions as a recovery-tool-definitions event."""
        agent = Agent("test", deps_type=None)

        @agent.tool_plain
        def my_tool(x: int) -> str:
            """Do something."""
            return str(x)

        mock_client = MagicMock()
        mock_langfuse_module.get_client.return_value = mock_client

        with patch.dict("sys.modules", {"langfuse": mock_langfuse_module}):
            _log_tool_definitions(agent, episode_id=42)

        mock_client.create_event.assert_called_once()
        call_kwargs = mock_client.create_event.call_args[1]
        self.assertEqual(call_kwargs["name"], "recovery-tool-definitions")
        self.assertEqual(len(call_kwargs["input"]["tools"]), 1)
        self.assertEqual(call_kwargs["input"]["tools"][0]["name"], "my_tool")
        self.assertEqual(call_kwargs["metadata"]["episode_id"], 42)
        self.assertEqual(call_kwargs["metadata"]["tool_count"], 1)

    def test_no_op_when_no_tools(self):
        """Does not call Langfuse when agent has no extractable tools."""
        fake_agent = MagicMock(spec=[])  # no _function_toolset

        # Should not raise
        _log_tool_definitions(fake_agent, episode_id=1)

    @patch("episodes.agents.agent.langfuse", create=True)
    def test_handles_langfuse_error_gracefully(self, mock_langfuse_module):
        """Swallows exceptions from Langfuse client."""
        agent = Agent("test", deps_type=None)

        @agent.tool_plain
        def failing_tool(x: int) -> str:
            """A tool."""
            return str(x)

        mock_langfuse_module.get_client.side_effect = RuntimeError("connection failed")

        with patch.dict("sys.modules", {"langfuse": mock_langfuse_module}):
            # Should not raise
            _log_tool_definitions(agent, episode_id=1)
